# Model Card: PawPal+ Scheduling and Slot Suggestion

## 1. Overview

**System name:** PawPal+
**Type:** Rule-based pet-care scheduler with a retrieval-augmented (RAG) time-slot suggester, built as a Streamlit app.

**What it does:**
- Tracks owners, pets and care tasks (walks, feeding, meds, grooming and so on).
- Builds a daily plan that fits the owner's available minutes, sorted by priority.
- Warns when two tasks share a start time.
- Handles daily and weekly recurring tasks.
- Suggests open time slots for a new task from a natural-language request, for example "Groom Mochi for 30 min tomorrow morning".

**Intended use:** Helping a busy pet owner plan a day of pet care. This is a class project and a learning tool.

**Not intended for:** Medical decisions, medication dosing, or anything where a missed or misplaced task could harm an animal. Check medication times yourself.

## 2. How it works

| Component | File | Approach |
|-----------|------|----------|
| Task, Pet, Owner, Scheduler | `pawpal_system.py` | Plain Python dataclasses and deterministic logic |
| Plan building | `Scheduler.build_plan` | Greedy: sort by priority, then preferred time, then shortest duration. Add tasks until the time budget runs out. |
| Free-slot finding | `Scheduler.find_free_slots` | Day window (08:00-21:00) minus merged intervals of timed tasks |
| Retrieval | `rag.py` `Retriever` | Small TF-IDF and cosine-similarity search over care-guidance tips plus the pet's existing tasks |
| Generation | `rag.py` `suggest_slot` | A pluggable `llm(prompt) -> str` function. The default is an offline template that picks the earliest free slot and quotes the top retrieved note. |
| Request parsing | `rag.py` `parse_request` | Regular expressions that pull out duration, date, time-of-day window and pet name |

**Important:** By default no external AI model is called. The "AI" suggestion is retrieval plus a template. A real LLM can be passed in through the `llm` parameter, but this card describes the default offline behavior unless you have connected one.

**Guardrail:** The free slots are computed by code, not by the model. If the generator's chosen time is not inside a computed free slot, the reply is rejected and the earliest free slot is used instead. This stops a model from suggesting a time that creates a conflict.

## 3. Inputs and outputs

**Inputs:**
- Owner name and available minutes for the day.
- Pets (name, species).
- Tasks (title, duration, priority, optional start time, frequency).
- Free-text slot requests.

**Outputs:**
- Ordered daily plan and a list of skipped tasks.
- Conflict warnings.
- Suggested start times with a short explanation and the retrieved context.

**Example:**

| Input | Output |
|-------|--------|
| Mochi groomed for 30 min | Suggested opening at 8:00 am |
| Mochi photoshoot, 30 min | Suggested time at 8:30 am |

## 4. Limitations and biases

- **Exact-match conflicts only.** `detect_conflicts` flags tasks with identical start times. A 08:00 to 08:30 task and an 08:15 task are not flagged. A test, `test_detect_conflicts_misses_overlap_without_identical_start_times`, documents this on purpose.
- **Greedy planning is not optimal.** A big task that doesn't fit is skipped. Smaller later tasks may still be scheduled, so the plan can be good but not the best possible.
- **Priority beats clock time.** A high-priority task is listed before an earlier low-priority one, so the plan is not always in time order.
- **Fixed day window.** Slot suggestions assume 08:00 to 21:00 unless told otherwise. This favors a typical daytime routine and does not suit night-shift owners.
- **Small, hand-written knowledge base.** Only 7 care tips, mostly about dogs and cats. Other species ("other") get little useful guidance. The tips are general and not veterinary advice.
- **Simple retrieval and parsing.** TF-IDF matches words, not meaning. The parser handles a few phrasings (morning, afternoon, evening, tomorrow, weekdays, "this week") and may misread others. Durations default to 30 minutes if none is found.
- **Untimed tasks don't block slots.** A task with no start time takes up plan minutes but not a time slot, so a suggested slot may overlap in real life with an untimed task.
- **Double-booking risk.** A suggested slot added as a new task alongside the original task shows it twice. Rename it or mark one complete.
- **Data is in memory only.** Nothing is saved after the app closes.

## 5. Testing

- **Automated:** `pytest` runs 39 tests, all passing at the time of writing.
- **Covered:** completing tasks, sorting (including ties and untimed tasks), recurrence (daily, weekly, month and year boundaries), overdue tasks, conflict detection, the time budget (exact fit, one minute over, zero minutes), empty inputs and filtering. For the suggestion feature: the guardrail rejecting invalid, empty or garbled model replies, a full day with no free slot, the offline fallback, retrieval of relevant tips, request parsing (defaults, minutes, hours, weekdays, unknown pet) and per-day suggestions.
- **What worked:** Edge cases around time budgets and recurrence were easy to test because the scheduler is deterministic.
- **What is weaker:** Retrieval quality is only tested on simple queries and was not measured at scale. The parser is tested on a handful of phrasings, so unusual wording such as "an hour and a half" is untested. No test uses a real LLM.

## 6. Human oversight

The owner decides. PawPal+ suggests slots and warns about conflicts but never changes the schedule on its own. Treat every suggestion as a draft to review, especially for medication and feeding.

## 7. Reflection

- **AI collaboration:** I used AI to help navigate the project, debug, and add code to the right files. I did not accept suggestions that didn't connect back to what I was trying to solve, and I checked each one against the question being asked.
- **What I learned:** The suggestion feature has a trade-off: a suggested slot and the original task can both appear in the calendar. That can be handled by renaming the suggested one, and the same feature is also useful for filling gaps between tasks with short or low-priority tasks.
- **What I would improve:** Detect real overlaps (not just identical start times), broaden the care guidance, save data between sessions, and add tests for the RAG and parsing code.


### What are the limitations or biases in your system?

The limitations in the system is that the same task repeats if you write it twice as it considers it a different task instead when writing differently. Ex: Photoshoot for Mochi and Mochi Dog Photoshoot.


### Could your AI be misused, and how would you prevent that?

The AI could be misused by having the task repeated twice instead of once but could be preventable by only writing the task once.

### What surprised you while testing your AI's reliability?
Something that surprise me while testing my AI's reliability was that it was able to anaylize the rest of the tasks and figure out a time placement for the task that is being requested. 


### Identify one suggestion you accepted and one you did not accept as written, and say why you rejected or changed it. It does not have to be a suggestion that was wrong: over-engineered, out of scope, harder to read, or a poor fit for your system all count. If nothing the AI suggested was outright wrong, look for one you still changed: shortened, simplified, renamed, or scoped down

The suggestion that I accepted was suggesting times that was being offered for tasks and the one that was rejected was having time slots for different days. 