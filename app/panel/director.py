"""The silent director: who speaks next, and what they are trying to get at.

Scores the whole panel on every candidate turn rather than rotating. A rotation
is detectable within three turns and it is wrong: after a well-reasoned answer
the right person to follow up is usually the one who just asked.

Deliberately a scoring function rather than a model call. It is instant, costs
nothing, is reproducible in a test, and can be explained to a candidate who asks
why the same interviewer came back twice — none of which is true of asking a
model to pick.

Ported from the original build. Kept pure so the interruption acceptance test
can drive it without a network.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from app.panel.roster import PANEL, Interviewer

# "open" is never chosen by scoring: it is the one turn that happens before the
# candidate has said anything for the director to score against.
Action = Literal["probe", "challenge", "ask", "clarify", "open"]

HEDGE_CUES: tuple[str, ...] = (
    "i guess",
    "i think maybe",
    "kind of",
    "more or less",
    "not sure",
    "or something",
    "pretty much",
    "probably",
    "roughly",
    "sort of",
)

# Words that suggest the candidate reasoned rather than asserted. A follow-up
# from the same interviewer is worth more after one of these.
REASONING_CUES: tuple[str, ...] = ("because", "result", "metric", "tradeoff")
EVIDENCE_CUES: tuple[str, ...] = ("%", "percent", "metric", "result", "measured", "users")


@dataclass
class PanelState:
    """What the director remembers between turns."""

    current_speaker_id: str | None = None
    question_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Decision:
    speaker: Interviewer
    action: Action
    objective: str
    rationale: str


def _objective(
    speaker: Interviewer, asked: int, text: str, has_evidence: bool
) -> tuple[Action, str]:
    """Pick what this turn is for, from what the candidate said and what has
    already been asked.

    `asked` is how many questions this interviewer has put so far, which is also
    the index of the next unused angle in their line of questioning. Without it
    every ordinary turn resolved to one of two fixed strings and the panel asked
    the same question all interview: not the model being dull, but the
    instruction being identical each time.
    """
    if any(cue in text for cue in ("am i audible", "can you hear me", "are you there")):
        return "clarify", "I can hear you. Are you ready to continue?"
    if any(cue in text for cue in ("i am ready", "i'm ready", "ready to begin", "let's begin")):
        return "ask", (
            "To begin, introduce yourself and describe a project relevant to this role."
        )
    if any(cue in text for cue in ("don't understand", "not able to understand", "rephrase")):
        return "clarify", (
            "Let's simplify: describe one project you worked on and what you personally did."
        )
    if any(cue in text for cue in ("don't know", "cannot answer", "can't answer", "skip this")):
        return "ask", (
            "Let's try a different one. How do you approach a task when the requirements "
            "are unclear?"
        )
    if asked < len(speaker.angles):
        # Work down their line of questioning. The first is an opener, the rest
        # push on what the previous answer left unsaid.
        return ("ask" if asked == 0 else "probe"), speaker.angles[asked]

    # Their arc is exhausted, so fall back to the two that always apply.
    if not has_evidence:
        return "probe", "What evidence would let us verify that claim?"
    return "challenge", "What tradeoff did you accept, and how did you measure the result?"


def choose_next(
    state: PanelState, candidate_text: str, panel: tuple[Interviewer, ...] = PANEL
) -> Decision:
    """Score every interviewer and hand the floor to the strongest fit."""
    text = candidate_text.lower()
    counts = Counter(state.question_counts)
    quietest = min((counts[member.id] for member in panel), default=0)

    scored: list[tuple[float, Interviewer]] = []
    for member in panel:
        score = -1.5 * counts[member.id]
        score += 3 if any(term in text for term in member.expertise) else 0
        score += (
            2
            if member.id == state.current_speaker_id
            and any(cue in text for cue in REASONING_CUES)
            else 0
        )
        score += 1 if counts[member.id] == quietest else 0
        scored.append((score, member))

    # Ties break on id so the same input always produces the same panel.
    speaker = max(scored, key=lambda item: (item[0], item[1].id))[1]

    has_evidence = any(cue in text for cue in EVIDENCE_CUES)
    hedges = [cue for cue in HEDGE_CUES if cue in text]
    action, objective = _objective(speaker, counts[speaker.id], text, has_evidence)

    return Decision(
        speaker=speaker,
        action=action,
        objective=objective,
        rationale=_rationale(speaker, counts[speaker.id], text, hedges, has_evidence),
    )


def _rationale(
    speaker: Interviewer, asked: int, text: str, hedges: list[str], has_evidence: bool
) -> str:
    """Why this interviewer, in words a candidate could be shown."""
    if any(term in text for term in speaker.expertise):
        reason = f"the answer moved onto {speaker.role.lower()} ground"
    elif asked == 0:
        reason = "they have not spoken yet"
    else:
        reason = "they have asked the fewest questions"
    if hedges:
        return f"{speaker.name} takes it because {reason}, and the answer hedged."
    if not has_evidence:
        return f"{speaker.name} takes it because {reason}, and no evidence was offered."
    return f"{speaker.name} takes it because {reason}."


def record(state: PanelState, decision: Decision) -> PanelState:
    """Advance the state after an interviewer has actually spoken."""
    counts = dict(state.question_counts)
    counts[decision.speaker.id] = counts.get(decision.speaker.id, 0) + 1
    return PanelState(current_speaker_id=decision.speaker.id, question_counts=counts)
