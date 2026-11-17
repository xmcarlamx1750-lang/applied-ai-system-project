"""Retrieval-augmented slot suggestions for PawPal.

Free slots are computed deterministically by Scheduler.find_free_slots.
Retrieval adds context (existing tasks + care guidance) so the generator can
pick the best slot and explain why. The generator is a pluggable callable
(`llm(prompt) -> str`); the default is an offline template so no API is needed.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable

from pawpal_system import Owner, Scheduler

CARE_GUIDANCE = [
    "Dogs need at least two walks a day; walk in the morning and early evening.",
    "Do not walk or play hard with a dog right after a meal; wait about an hour.",
    "Grooming and brushing is best when a pet is calm, such as after a walk.",
    "Cats prefer feeding at consistent times; keep meals spaced 8 to 12 hours apart.",
    "Medication must be given at a fixed time every day; never move it.",
    "Puppies and kittens need shorter, more frequent play and feeding sessions.",
    "Training sessions work best short (10 to 15 minutes) when the pet is alert.",
]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass
class Retriever:
    """Tiny TF-IDF retriever over text chunks (swap for embeddings later)."""

    docs: list[str]

    def __post_init__(self) -> None:
        self._tokens = [Counter(tokenize(d)) for d in self.docs]
        n = len(self.docs)
        df = Counter(w for c in self._tokens for w in c)
        self._idf = {w: math.log((n + 1) / (k + 1)) + 1 for w, k in df.items()}

    def _vec(self, counts: Counter) -> dict[str, float]:
        return {w: c * self._idf.get(w, 0.0) for w, c in counts.items()}

    @staticmethod
    def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
        dot = sum(v * b.get(w, 0.0) for w, v in a.items())
        norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
            sum(v * v for v in b.values())
        )
        return dot / norm if norm else 0.0

    def search(self, query: str, k: int = 4) -> list[str]:
        q = self._vec(Counter(tokenize(query)))
        scored = [(self._cosine(q, self._vec(c)), d) for c, d in zip(self._tokens, self.docs)]
        return [d for s, d in sorted(scored, key=lambda x: -x[0])[:k] if s > 0]


def task_chunks(owner: Owner) -> list[str]:
    """One text chunk per task, describing the pet's existing schedule."""
    return [
        f"{pet.name} ({pet.species}) - {t.title}, {t.duration_minutes} min, "
        f"{'at ' + t.time if t.time else 'untimed'}, {t.frequency}, {t.priority} priority"
        for pet in owner.pets
        for t in pet.pending_tasks()
    ]


def build_prompt(request: str, slots: list[tuple[str, str]], context: list[str]) -> str:
    return (
        "You are a pet-care scheduling assistant.\n"
        f"Request: {request}\n"
        "Free slots (choose ONLY from these, format HH:MM-HH:MM):\n"
        + "\n".join(f"- {s}-{e}" for s, e in slots)
        + "\nContext:\n"
        + "\n".join(f"- {c}" for c in context)
        + "\nReply with the chosen start time as HH:MM, then a one-sentence reason."
    )


def offline_llm(prompt: str) -> str:
    """Fallback 'generator': picks the first free slot and cites top context."""
    slots = re.findall(r"^- (\d\d:\d\d)-\d\d:\d\d$", prompt, re.M)
    context = prompt.split("Context:\n", 1)[-1].splitlines()
    note = context[0].lstrip("- ") if context and context[0] else "it is free"
    return f"{slots[0]} - earliest open slot; note: {note}" if slots else ""

@dataclass
class Suggestion:
    start: str | None
    explanation: str
    candidates: list[tuple[str, str]]
    context: list[str]


def suggest_slot(
    scheduler: Scheduler,
    request: str,
    duration: int,
    llm: Callable[[str], str] = offline_llm,
    k: int = 4,
    day_start: str = "08:00",
    day_end: str = "21:00",
) -> Suggestion:
    """Retrieve context, compute free slots, let the generator choose, validate."""
    candidates = scheduler.find_free_slots(duration, day_start, day_end)
    if not candidates:
        return Suggestion(None, "No free slot is long enough today.", [], [])
    retriever = Retriever(CARE_GUIDANCE + task_chunks(scheduler.owner))
    context = retriever.search(request, k)
    answer = llm(build_prompt(request, candidates, context)).strip()
    match = re.match(r"(\d\d:\d\d)", answer)
    # Guardrail: the chosen start must lie inside a computed free slot.
    valid = match and any(s <= match.group(1) <= e for s, e in candidates)
    if not valid:
        start = candidates[0][0]
        return Suggestion(start, f"Earliest free slot (model reply rejected: {answer!r}).", candidates, context)
    return Suggestion(match.group(1), answer, candidates, context)


# --- Natural-language request parsing -------------------------------------

WINDOWS = {
    "morning": ("08:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "21:00"),
}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class ParsedRequest:
    title: str
    pet: str | None = None
    duration: int = 30
    dates: list[date] = field(default_factory=list)
    window: tuple[str, str] = ("08:00", "21:00")


def parse_request(text: str, owner: Owner, today: date | None = None) -> ParsedRequest:
    """Turn e.g. 'Groom Rex for 30 min tomorrow morning' into structured fields.

    Rule-based so it works offline; an LLM could fill the same dataclass.
    Defaults: 30 min, today, whole day. 'this week' gives the next 7 days.
    """
    today = today or date.today()
    low = text.lower()

    duration = 30
    m = re.search(r"(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m)\b", low)
    if m:
        n = int(m.group(1))
        duration = n * 60 if m.group(2).startswith("h") else n

    if "this week" in low or "next 7" in low:
        dates = [today + timedelta(days=i) for i in range(7)]
    elif "tomorrow" in low:
        dates = [today + timedelta(days=1)]
    else:
        dates = [today]
        for i, name in enumerate(WEEKDAYS):
            if name in low:
                dates = [today + timedelta(days=(i - today.weekday()) % 7)]
                break

    window = next((w for name, w in WINDOWS.items() if name in low), ("08:00", "21:00"))
    pet = next((p.name for p in owner.pets if p.name.lower() in low), None)
    return ParsedRequest(text.strip(), pet, duration, dates, window)


def find_slots_in_range(
    owner: Owner, req: ParsedRequest
) -> list[tuple[date, list[tuple[str, str]]]]:
    """Free slots per requested date (days with no fitting gap are omitted)."""
    out = []
    for d in req.dates:
        slots = Scheduler(owner, d).find_free_slots(req.duration, *req.window)
        if slots:
            out.append((d, slots))
    return out


def suggest_from_text(
    owner: Owner,
    text: str,
    llm: Callable[[str], str] = offline_llm,
    today: date | None = None,
) -> tuple[ParsedRequest, list[tuple[date, Suggestion]]]:
    """Parse the request, then give one suggestion per day that has room."""
    req = parse_request(text, owner, today)
    results = []
    for d, _ in find_slots_in_range(owner, req):
        sug = suggest_slot(Scheduler(owner, d), text, req.duration, llm, 4, *req.window)
        results.append((d, sug))
    return req, results
