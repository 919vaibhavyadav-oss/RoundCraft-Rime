"""The lookup an interviewer runs, and the fence that discards a stale one.

The event brief's proof procedure is explicit: introduce a fixed delay into a
tool call, interrupt while it runs, and verify that "stale tool results are not
spoken as current" and that "background work is cancelled or reconciled
correctly".

The delay and the speaking belong to the live run. What is decided without a
network - whether a result that arrives after a handover is still allowed to be
used - is decided by the same generation fence as everything else, and is
settled here.
"""

import inspect

from app.agent import PanelAgent
from app.panel.benchmarks import BENCHMARKS, find_benchmark, known_metrics
from app.panel.floor import SpokenWord
from app.panel.session import InterviewSession


class TestFindBenchmark:
    def test_it_matches_a_claim_in_the_candidate_s_own_words(self) -> None:
        found = find_benchmark("we moved retention by four percent")
        assert found is not None
        assert found.metric == "retention"

    def test_it_matches_an_alias_a_candidate_would_actually_say(self) -> None:
        found = find_benchmark("onboarding got a lot better")
        assert found is not None
        assert found.metric == "activation"

    def test_an_unknown_metric_returns_nothing_rather_than_a_guess(self) -> None:
        """An interviewer with no benchmark must say so, not invent one."""
        assert find_benchmark("our Net Promoter Score went up") is None

    def test_matching_ignores_case(self) -> None:
        assert find_benchmark("CHURN dropped") is not None

    def test_every_benchmark_can_be_spoken_as_one_sentence(self) -> None:
        for benchmark in BENCHMARKS:
            spoken = benchmark.spoken()
            assert benchmark.metric in spoken
            assert spoken.endswith(".")

    def test_every_benchmark_is_reachable_by_its_own_name(self) -> None:
        """A metric nothing can match is a benchmark that never gets used."""
        for benchmark in BENCHMARKS:
            found = find_benchmark(f"our {benchmark.metric} numbers")
            assert found is not None, f"{benchmark.metric} is unreachable"
            assert found.metric == benchmark.metric


class TestToolDescription:
    def test_the_tool_lists_every_metric_it_can_look_up(self) -> None:
        """The model picks the tool from this text, so it must not drift."""
        doc = inspect.getdoc(PanelAgent.check_benchmark) or ""
        for metric in known_metrics():
            assert metric in doc, f"{metric} missing from the tool description"


class TestStaleLookupsAreFenced:
    """What the brief calls reconciling background work correctly."""

    def test_a_lookup_that_outlives_its_turn_is_no_longer_accepted(self) -> None:
        session = InterviewSession()
        session.candidate_said("We moved retention by four percent.")
        asked_at = session.generation
        session.interviewer_spoke(asked_at, [SpokenWord("How", 0), SpokenWord("did", 120)])

        # The lookup is still running when the candidate cuts in.
        session.candidate_interrupted(at_ms=session.heard_ms() + 1)

        assert session.floor.accepts(asked_at) is False

    def test_a_lookup_that_finishes_inside_its_turn_is_still_accepted(self) -> None:
        session = InterviewSession()
        session.candidate_said("We moved retention by four percent.")
        asked_at = session.generation
        session.interviewer_spoke(asked_at, [SpokenWord("How", 0)])

        assert session.floor.accepts(asked_at) is True

    def test_the_answer_to_an_abandoned_question_never_reaches_the_transcript(self) -> None:
        """The failure the fence exists to prevent, stated for tool results."""
        session = InterviewSession()
        session.candidate_said("We moved retention by four percent.")
        asked_at = session.generation
        session.interviewer_spoke(asked_at, [SpokenWord("How", 0), SpokenWord("did", 120)])
        session.candidate_interrupted(at_ms=session.heard_ms() + 1)

        # A different interviewer is now speaking.
        session.candidate_said("Sorry, I meant activation, not retention.")

        # The retention lookup finally returns and tries to be spoken.
        landed = session.interviewer_finished(
            asked_at, "Typical retention is a 2 to 3 percent lift per quarter."
        )

        assert landed is False
        assert all("2 to 3 percent" not in turn.text for turn in session.transcript)
