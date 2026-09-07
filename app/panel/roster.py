"""Who sits on the panel.

Three interviewers, not five. The event brief is explicit that a focused product
with one convincingly solved voice problem beats a broad assistant, and three is
enough to demonstrate the thing this build is actually about: that interrupting
one interviewer hands the floor to a different voice.

Each entry pairs an interviewer with the Rime speaker they talk in. Expertise
terms are what the director matches a candidate's answer against, so they are
written as words a candidate would actually say, not as internal category names.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Interviewer:
    id: str
    name: str
    role: str
    expertise: tuple[str, ...]
    brief: str
    competency: str = ""
    interruptable: bool = True
    _: dict[str, str] = field(default_factory=dict, repr=False, compare=False)


PANEL: tuple[Interviewer, ...] = (
    Interviewer(
        id="hiring-manager",
        name="Maya Chen",
        role="Hiring Manager",
        expertise=("team", "leadership", "stakeholder", "conflict", "ownership"),
        brief=(
            "Test judgement, ownership and how the candidate works with other people. "
            "Ask one focused follow-up at a time."
        ),
        competency="leadership",
    ),
    Interviewer(
        id="product-sense",
        name="Noah Williams",
        role="Product Sense Interviewer",
        expertise=("customer", "user", "problem", "prioritis", "prioritiz", "tradeoff"),
        brief=(
            "Test customer insight and prioritisation. Push on why this problem and "
            "not another one."
        ),
        competency="product_judgment",
    ),
    Interviewer(
        id="analytics",
        name="Priya Rao",
        role="Analytics Interviewer",
        expertise=("metric", "measure", "experiment", "percent", "data", "retention"),
        brief=(
            "Test quantitative reasoning. Ask how a claim was measured and what the "
            "guardrail was."
        ),
        competency="analytics",
    ),
)

BY_ID: dict[str, Interviewer] = {member.id: member for member in PANEL}


def interviewer(panelist_id: str) -> Interviewer:
    """Resolve an interviewer, defaulting to the first rather than failing a turn."""
    return BY_ID.get(panelist_id, PANEL[0])


def _join_names(parts: list[str]) -> str:
    """Join names the way a person reads them aloud: "a, b and c"."""
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def opening_line() -> str:
    """What the hiring manager says before the candidate has spoken."""
    lead, *rest = PANEL
    if not rest:
        return f"Hi, I'm {lead.name}. Walk me through a product you shipped recently."
    colleagues = _join_names(
        [f"{member.name} on {member.competency.replace('_', ' ')}" for member in rest]
    )
    return (
        f"Hi, I'm {lead.name}, and I'm leading this panel with {colleagues}. "
        "To get us started, walk me through a product you shipped recently."
    )
