"""What an interviewer checks when a candidate cites a number.

This exists to give the panel a reason to do work that takes time. An analytics
interviewer who hears "retention went up four percent" reaches for the
benchmark before deciding whether that is impressive, and that lookup is the
thing a candidate can interrupt while it is still in flight.

The event brief asks for exactly this shape of proof: introduce a fixed delay
into a tool call, interrupt while it runs, and show that a stale result is
never spoken as current. The delay lives in configuration rather than here, so
the demo can lengthen it without touching the data.

The figures are illustrative industry ranges for a mock interview, not
measurements of any real company. They are deliberately coarse: the point is
that a lookup happens and can be interrupted, not that the numbers are
authoritative.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Benchmark:
    """A rough band for one product metric, as an interviewer would quote it."""

    metric: str
    typical: str
    strong: str
    follow_up: str

    def spoken(self) -> str:
        """One sentence an interviewer can say out loud."""
        return (
            f"For {self.metric}, typical is {self.typical} and strong is {self.strong}. "
            f"{self.follow_up}"
        )


BENCHMARKS: tuple[Benchmark, ...] = (
    Benchmark(
        metric="retention",
        typical="a 2 to 3 percent lift per quarter",
        strong="anything above 5 percent",
        follow_up="Ask which cohort moved, and over what window.",
    ),
    Benchmark(
        metric="activation",
        typical="30 to 40 percent of signups",
        strong="above 55 percent",
        follow_up="Ask how activation was defined before the change.",
    ),
    Benchmark(
        metric="conversion",
        typical="2 to 4 percent of visitors",
        strong="above 8 percent",
        follow_up="Ask whether the traffic mix stayed constant.",
    ),
    Benchmark(
        metric="engagement",
        typical="a DAU to MAU ratio near 20 percent",
        strong="above 35 percent",
        follow_up="Ask what a daily active user actually did.",
    ),
    Benchmark(
        metric="churn",
        typical="4 to 6 percent monthly for self-serve",
        strong="below 2 percent",
        follow_up="Ask whether churn is measured on revenue or on accounts.",
    ),
)

# Words a candidate is likely to say, mapped to the benchmark they refer to.
# Written as spoken language rather than as internal metric names, because what
# arrives here is a transcript.
_ALIASES: dict[str, str] = {
    "retention": "retention",
    "retained": "retention",
    "stickiness": "retention",
    "activation": "activation",
    "activated": "activation",
    "onboarding": "activation",
    "conversion": "conversion",
    "converted": "conversion",
    "signup rate": "conversion",
    "engagement": "engagement",
    "dau": "engagement",
    "mau": "engagement",
    "daily active": "engagement",
    "churn": "churn",
    "attrition": "churn",
    "cancelled": "churn",
}

_BY_METRIC: dict[str, Benchmark] = {b.metric: b for b in BENCHMARKS}


def find_benchmark(claim: str) -> Benchmark | None:
    """Resolve a spoken claim to a benchmark, or None when nothing matches.

    Returning None matters: an interviewer who has no benchmark should say so
    rather than invent one, and this product's whole posture is that an
    unsupported number is not evidence.
    """
    lowered = claim.lower()
    for phrase, metric in _ALIASES.items():
        if phrase in lowered:
            return _BY_METRIC[metric]
    return None


def known_metrics() -> tuple[str, ...]:
    """The metrics that can be looked up, for the tool's description."""
    return tuple(b.metric for b in BENCHMARKS)
