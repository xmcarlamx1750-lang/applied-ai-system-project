from datetime import date, timedelta

from pawpal_system import Owner, Pet, Scheduler, Task

TODAY = date(2026, 3, 10)


def make_scheduler(*pets, minutes=120, plan_date=TODAY):
    owner = Owner("Sam", available_minutes=minutes)
    for pet in pets:
        owner.add_pet(pet)
    return Scheduler(owner, plan_date)


def test_mark_complete_changes_status():
    task = Task("Morning walk", 20)
    assert task.completed is False

    task.mark_complete()

    assert task.completed is True


def test_add_task_increases_pet_task_count():
    pet = Pet("Rex", "dog")
    assert len(pet.tasks) == 0

    pet.add_task(Task("Morning walk", 20))

    assert len(pet.tasks) == 1


# --- Sorting ---


def test_sort_by_time_orders_numerically_and_puts_untimed_last():
    sched = make_scheduler()
    tasks = [
        Task("untimed", 5),
        Task("late", 5, time="23:59"),
        Task("midnight", 5, time="00:00"),
        Task("morning", 5, time="09:00"),
        Task("mid", 5, time="10:30"),
    ]

    result = [t.title for t in sched.sort_by_time(tasks)]

    assert result == ["midnight", "morning", "mid", "late", "untimed"]


def test_sort_by_time_is_stable_for_ties_and_does_not_mutate_input():
    sched = make_scheduler()
    a = Task("a", 5, time="08:00")
    b = Task("b", 5, time="08:00")
    c = Task("c", 5, time="07:00")
    original = [a, b, c]

    result = sched.sort_by_time(original)

    assert result == [c, a, b]
    assert original == [a, b, c]


def test_sort_tasks_priority_beats_time_then_duration_breaks_ties():
    sched = make_scheduler()
    low_early = Task("low early", 5, priority="low", time="07:00")
    high_late = Task("high late", 30, priority="high", time="18:00")
    high_late_short = Task("high late short", 10, priority="high", time="18:00")

    result = sched.sort_tasks([low_early, high_late, high_late_short])

    assert result == [high_late_short, high_late, low_early]


def test_sorting_empty_list_returns_empty_list():
    sched = make_scheduler()

    assert sched.sort_tasks([]) == []
    assert sched.sort_by_time([]) == []


# --- Recurring tasks ---


def test_daily_task_completion_creates_next_day_task():
    pet = Pet("Rex", "dog")
    task = Task("Walk", 20, frequency="daily", due_date=TODAY)
    pet.add_task(task)

    following = pet.complete_task(task)

    assert task.completed is True
    assert following is not None
    assert following.completed is False
    assert following.due_date == TODAY + timedelta(days=1)
    assert following in pet.tasks and len(pet.tasks) == 2


def test_weekly_task_completion_creates_task_seven_days_later():
    pet = Pet("Rex", "dog")
    task = Task("Bath", 30, frequency="weekly", due_date=TODAY)
    pet.add_task(task)

    following = pet.complete_task(task)

    assert following.due_date == TODAY + timedelta(days=7)


def test_once_task_does_not_recur():
    pet = Pet("Rex", "dog")
    task = Task("Vet visit", 60, frequency="once", due_date=TODAY)
    pet.add_task(task)

    assert pet.complete_task(task) is None
    assert len(pet.tasks) == 1


def test_unknown_frequency_does_not_recur():
    assert Task("Trim nails", 10, frequency="monthly").next_occurrence() is None


def test_recurrence_without_due_date_counts_from_today():
    following = Task("Walk", 20, frequency="daily").next_occurrence()

    assert following.due_date == date.today() + timedelta(days=1)


def test_recurrence_crosses_month_and_year_boundaries():
    new_year = Task("Walk", 20, due_date=date(2026, 12, 31)).next_occurrence()
    leap_day = Task("Walk", 20, due_date=date(2028, 2, 28)).next_occurrence()

    assert new_year.due_date == date(2027, 1, 1)
    assert leap_day.due_date == date(2028, 2, 29)


# --- Scheduler: recurrence interactions ---


def test_next_occurrence_is_held_back_until_its_due_date():
    pet = Pet("Rex", "dog")
    task = Task("Walk", 20, frequency="daily", due_date=TODAY)
    pet.add_task(task)
    pet.complete_task(task)

    today_plan = make_scheduler(pet, plan_date=TODAY).build_plan()
    tomorrow_plan = make_scheduler(
        pet, plan_date=TODAY + timedelta(days=1)
    ).build_plan()

    assert today_plan == []
    assert [t.due_date for t in tomorrow_plan] == [TODAY + timedelta(days=1)]


def test_overdue_tasks_are_included_and_completed_tasks_are_not():
    pet = Pet("Rex", "dog")
    overdue = Task("Overdue", 10, due_date=TODAY - timedelta(days=3))
    done = Task("Done", 10, completed=True)
    pet.tasks.extend([overdue, done])

    assert make_scheduler(pet).get_pending_tasks() == [overdue]


# --- Scheduler: conflicts ---


def test_detect_conflicts_flags_same_time_across_pets():
    rex, mia = Pet("Rex", "dog"), Pet("Mia", "cat")
    rex.add_task(Task("Walk", 20, time="08:00"))
    mia.add_task(Task("Feed", 5, time="08:00"))

    warnings = make_scheduler(rex, mia).detect_conflicts()

    assert len(warnings) == 1
    assert "08:00" in warnings[0] and "Rex" in warnings[0] and "Mia" in warnings[0]


def test_detect_conflicts_ignores_untimed_completed_and_future_tasks():
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Untimed A", 5))
    pet.add_task(Task("Untimed B", 5))
    pet.add_task(Task("Done", 5, time="09:00", completed=True))
    pet.add_task(Task("Active", 5, time="09:00"))
    pet.add_task(Task("Future", 5, time="09:00", due_date=TODAY + timedelta(days=1)))

    assert make_scheduler(pet).detect_conflicts() == []


def test_detect_conflicts_misses_overlap_without_identical_start_times():
    # Known limitation: only exact "HH:MM" matches are detected.
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Long walk", 60, time="09:00"))
    pet.add_task(Task("Feed", 5, time="09:30"))

    assert make_scheduler(pet).detect_conflicts() == []


def test_detect_conflicts_with_no_tasks_returns_empty_list():
    assert make_scheduler(Pet("Rex", "dog")).detect_conflicts() == []


# --- Scheduler: time budget ---


def test_task_that_exactly_fills_budget_fits_but_one_minute_over_is_skipped():
    pet = Pet("Rex", "dog")
    exact = Task("Exact", 60, priority="high")
    over = Task("Over", 1, priority="low")
    pet.tasks.extend([exact, over])

    sched = make_scheduler(pet, minutes=60)
    sched.build_plan()

    assert sched.plan == [exact]
    assert sched.skipped == [over]


def test_greedy_plan_skips_big_task_but_still_schedules_later_small_ones():
    pet = Pet("Rex", "dog")
    first = Task("First", 40, priority="high")
    big = Task("Big", 50, priority="medium")
    small = Task("Small", 10, priority="low")
    pet.tasks.extend([first, big, small])

    sched = make_scheduler(pet, minutes=60)
    sched.build_plan()

    assert sched.plan == [first, small]
    assert sched.skipped == [big]


def test_zero_available_minutes_skips_everything():
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Walk", 20))

    sched = make_scheduler(pet, minutes=0)
    sched.build_plan()

    assert sched.plan == [] and len(sched.skipped) == 1


def test_scheduler_with_no_pets_or_tasks_builds_empty_plan_and_explains():
    sched = make_scheduler()

    assert sched.build_plan() == []
    assert "0/120 min used" in sched.explain_plan()


# --- Scheduler: filtering ---


def test_filter_tasks_by_pet_name_is_case_insensitive_and_by_completion():
    rex, mia = Pet("Rex", "dog"), Pet("Mia", "cat")
    walk = Task("Walk", 20, completed=True)
    feed = Task("Feed", 5)
    nap = Task("Nap", 5)
    rex.tasks.extend([walk, feed])
    mia.tasks.append(nap)
    sched = make_scheduler(rex, mia)

    assert sched.filter_tasks(pet_name="REX") == [walk, feed]
    assert sched.filter_tasks(completed=False) == [feed, nap]
    assert sched.filter_tasks(pet_name="Ghost") == []
    assert sched.filter_tasks() == [walk, feed, nap]


def test_find_free_slots_skips_busy_time():
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Walk", 60, time="09:00"))
    pet.add_task(Task("Meds", 15, time="12:00"))
    sched = make_scheduler(pet)

    slots = sched.find_free_slots(45)

    assert slots == [("08:00", "09:00"), ("10:00", "12:00"), ("12:15", "21:00")]


def test_suggest_slot_rejects_invalid_llm_answer():
    from rag import suggest_slot

    pet = Pet("Rex", "dog")
    pet.add_task(Task("Walk", 60, time="08:00"))
    sched = make_scheduler(pet)

    result = suggest_slot(sched, "groom Rex after a walk", 30, llm=lambda p: "08:30 sure")

    assert result.start == "09:00"  # 08:30 is busy, falls back to earliest free


def test_suggest_slot_uses_valid_llm_answer_and_context():
    from rag import suggest_slot

    sched = make_scheduler(Pet("Rex", "dog"))

    result = suggest_slot(sched, "grooming brushing", 30, llm=lambda p: "10:00 calm")

    assert result.start == "10:00"
    assert any("Grooming" in c for c in result.context)


def test_parse_request_extracts_fields():
    from rag import parse_request

    owner = Owner("Sam")
    owner.add_pet(Pet("Rex", "dog"))

    req = parse_request("Groom Rex for 1 hour tomorrow morning", owner, TODAY)

    assert (req.pet, req.duration) == ("Rex", 60)
    assert req.dates == [TODAY + timedelta(days=1)]
    assert req.window == ("08:00", "12:00")


def test_find_slots_in_range_covers_week():
    from rag import find_slots_in_range, parse_request

    pet = Pet("Rex", "dog")
    sched = make_scheduler(pet)

    req = parse_request("walk Rex 20 min this week", sched.owner, TODAY)

    assert len(find_slots_in_range(sched.owner, req)) == 7


def test_book_slot_adds_task_and_blocks_conflicts():
    import pytest

    pet = Pet("Rex", "dog")
    sched = make_scheduler(pet)

    task = sched.book_slot(pet, "Groom", 30, "10:00")

    assert task in pet.tasks and task.time == "10:00"
    with pytest.raises(ValueError):
        sched.book_slot(pet, "Bath", 30, "10:15")


def test_available_starts_only_where_duration_fits():
    pet = Pet("Rex", "dog")
    pet.add_task(Task("Walk", 60, time="09:00"))
    sched = make_scheduler(pet)

    starts = sched.available_starts(30, 15, "08:00", "10:30")

    assert starts == ["08:00", "08:15", "08:30", "10:00"]


# --- Extra coverage for the suggestion (RAG) feature ---------------------


def test_suggest_slot_returns_none_when_day_is_full():
    from rag import suggest_slot

    pet = Pet("Rex", "dog")
    pet.add_task(Task("Busy all day", 13 * 60, time="08:00"))  # 08:00 to 21:00
    sched = make_scheduler(pet)

    result = suggest_slot(sched, "groom Rex", 30)

    assert result.start is None
    assert result.candidates == []


def test_suggest_slot_falls_back_when_llm_reply_is_empty_or_garbled():
    from rag import suggest_slot

    sched = make_scheduler(Pet("Rex", "dog"))

    empty = suggest_slot(sched, "groom Rex", 30, llm=lambda p: "")
    garbled = suggest_slot(sched, "groom Rex", 30, llm=lambda p: "sometime later")

    assert empty.start == "08:00"
    assert garbled.start == "08:00"


def test_default_offline_generator_picks_earliest_free_slot():
    from rag import suggest_slot

    pet = Pet("Rex", "dog")
    pet.add_task(Task("Walk", 60, time="08:00"))
    sched = make_scheduler(pet)

    result = suggest_slot(sched, "brush Rex", 30)

    assert result.start == "09:00"


def test_retriever_finds_relevant_tip_and_ignores_unrelated_query():
    from rag import CARE_GUIDANCE, Retriever

    retriever = Retriever(CARE_GUIDANCE)

    assert "Medication" in retriever.search("medication", k=1)[0]
    assert retriever.search("zzzz qqqq") == []


def test_parse_request_uses_defaults_when_nothing_is_specified():
    from rag import parse_request

    owner = Owner("Sam")
    owner.add_pet(Pet("Rex", "dog"))

    req = parse_request("walk Rex", owner, TODAY)

    assert req.pet == "Rex"
    assert req.duration == 30
    assert req.dates == [TODAY]
    assert req.window == ("08:00", "21:00")


def test_parse_request_handles_minutes_hours_and_weekdays():
    from rag import parse_request

    owner = Owner("Sam")

    assert parse_request("bath 45 minutes", owner, TODAY).duration == 45
    assert parse_request("bath 2 hrs", owner, TODAY).duration == 120
    # TODAY is a Tuesday, so "friday" is 3 days ahead
    assert parse_request("bath on friday", owner, TODAY).dates == [TODAY + timedelta(days=3)]


def test_parse_request_unknown_pet_is_none():
    from rag import parse_request

    owner = Owner("Sam")
    owner.add_pet(Pet("Rex", "dog"))

    assert parse_request("groom Ghost", owner, TODAY).pet is None


def test_suggest_from_text_gives_one_suggestion_per_day_with_room():
    from rag import suggest_from_text

    sched = make_scheduler(Pet("Rex", "dog"))

    req, results = suggest_from_text(sched.owner, "walk Rex 30 min tomorrow", today=TODAY)

    assert len(results) == 1
    assert results[0][0] == TODAY + timedelta(days=1)
    assert results[0][1].start == "08:00"


def test_suggest_from_text_skips_days_with_no_room():
    from rag import suggest_from_text

    pet = Pet("Rex", "dog")
    pet.add_task(Task("Busy all day", 13 * 60, time="08:00"))  # no due date: blocks every day
    sched = make_scheduler(pet)

    _, results = suggest_from_text(sched.owner, "walk Rex 30 min this week", today=TODAY)

    assert results == []
