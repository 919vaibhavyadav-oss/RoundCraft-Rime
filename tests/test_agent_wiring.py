"""The seams between LiveKit's events and the tested panel logic.

`app/agent.py` is wiring, and wiring can only be fully proven by running it
against a room. But three of its decisions are pure and can be pinned here, and
they are the three that would silently corrupt a transcript if they were wrong:

  - how a Rime word timestamp becomes a `SpokenWord`
  - where an interruption is cut, given only the words that were played
  - who opens the interview, before anyone has said anything to score

Importing `app.agent` is deliberately avoided: it pulls in the whole LiveKit
worker stack for no gain. What it depends on lives in `app.panel`, so that is
what is tested.
"""

from app.panel.floor import FloorGuard, SpokenWord, word_from_timing
from app.panel.roster import PANEL, _join_names, opening_line
from app.panel.session import InterviewSession


class TestWordFromTiming:
    """Rime reports word start times; LiveKit's fallback reports end times."""

    def test_a_start_time_is_preferred(self) -> None:
        word = word_from_timing("tradeoff", start_s=0.15, end_s=0.4)
        assert word == SpokenWord(text="tradeoff", start_ms=150)

    def test_an_end_time_is_used_when_alignment_is_unavailable(self) -> None:
        """Without Rime's websocket mode there is no start time, only pacing."""
        word = word_from_timing("tradeoff", start_s=None, end_s=0.4)
        assert word == SpokenWord(text="tradeoff", start_ms=400)

    def test_an_untimed_word_is_dropped_rather_than_placed_at_zero(self) -> None:
        """Recording it at 0ms would make every untimed word look heard first."""
        assert word_from_timing("tradeoff", start_s=None, end_s=None) is None

    def test_whitespace_deltas_are_not_words(self) -> None:
        assert word_from_timing(" ", start_s=0.2, end_s=0.3) is None

    def test_surrounding_whitespace_is_stripped(self) -> None:
        word = word_from_timing(" scope ", start_s=1.25, end_s=1.4)
        assert word is not None
        assert word.text == "scope"

    def test_a_negative_timestamp_cannot_precede_the_utterance(self) -> None:
        word = word_from_timing("what", start_s=-0.01, end_s=0.1)
        assert word is not None
        assert word.start_ms == 0


class TestHeardSoFar:
    """The cut point the live agent uses, derived from played words alone."""

    def test_nothing_played_means_nothing_heard(self) -> None:
        guard = FloorGuard()
        guard.take_floor("analytics")
        assert guard.heard_ms == 0

    def test_it_tracks_the_last_word_played(self) -> None:
        guard = FloorGuard()
        generation = guard.take_floor("analytics")
        guard.note_spoken(generation, [SpokenWord("How", 0), SpokenWord("did", 120)])
        assert guard.heard_ms == 120

    def test_it_resets_when_the_floor_changes_hands(self) -> None:
        guard = FloorGuard()
        first = guard.take_floor("analytics")
        guard.note_spoken(first, [SpokenWord("How", 0), SpokenWord("did", 900)])
        guard.take_floor("product-sense")
        assert guard.heard_ms == 0

    def test_cutting_just_past_the_last_word_keeps_every_played_word(self) -> None:
        """The rule the live agent relies on: whatever arrived was heard."""
        session = InterviewSession()
        session.candidate_said("We measured retention at 22 percent.")
        session.interviewer_spoke(
            session.generation,
            [SpokenWord("How", 0), SpokenWord("did", 120), SpokenWord("you", 260)],
        )

        cut = session.candidate_interrupted(at_ms=session.heard_ms() + 1)

        assert cut is not None
        assert cut.heard == "How did you"
        assert cut.unheard == ""


class TestPanelOpening:
    def test_the_hiring_manager_opens_the_interview(self) -> None:
        session = InterviewSession()
        decision = session.panel_opened()

        assert decision.speaker is PANEL[0]
        assert decision.speaker.id == "hiring-manager"
        assert decision.action == "open"

    def test_the_opening_turn_holds_the_floor_like_any_other(self) -> None:
        """So the first sentence is interruptible on the same terms as the rest."""
        session = InterviewSession()
        session.panel_opened()

        assert session.current_speaker is not None
        assert session.generation == 1

    def test_an_opening_that_plays_in_full_is_recorded(self) -> None:
        session = InterviewSession()
        session.panel_opened()
        session.interviewer_spoke(session.generation, [SpokenWord("Welcome", 0)])

        assert session.interviewer_finished(session.generation, "Welcome to the panel.") is True
        assert session.transcript[0].speaker_id == "hiring-manager"

    def test_an_opening_cut_short_keeps_only_what_played(self) -> None:
        session = InterviewSession()
        session.panel_opened()
        session.interviewer_spoke(
            session.generation, [SpokenWord("Welcome", 0), SpokenWord("aboard", 300)]
        )

        cut = session.candidate_interrupted(at_ms=200)

        assert cut is not None
        assert cut.heard == "Welcome"
        assert cut.unheard == "aboard"

    def test_the_candidate_answers_the_opening_and_the_director_takes_over(self) -> None:
        session = InterviewSession()
        session.panel_opened()
        session.interviewer_spoke(session.generation, [SpokenWord("Welcome", 0)])
        session.interviewer_finished(session.generation, "Welcome. Tell me what you shipped.")

        decision = session.candidate_said("We moved retention by 4 percent with an experiment.")

        assert decision.speaker.id == "analytics"


class TestOpeningLine:
    """The greeting is spoken, not generated, so its wording is ours to pin.

    The model cannot produce this turn at all: a request carrying only system
    messages is rejected by the chat template with "No user query found in
    messages", because there is no candidate turn yet to answer.
    """

    def test_it_names_the_lead_and_the_rest_of_the_panel(self) -> None:
        line = opening_line()
        for member in PANEL:
            assert member.name in line

    def test_it_asks_the_candidate_to_start(self) -> None:
        assert "walk me through" in opening_line().lower()

    def test_names_read_the_way_a_person_says_them(self) -> None:
        assert _join_names(["a"]) == "a"
        assert _join_names(["a", "b"]) == "a and b"
        assert _join_names(["a", "b", "c"]) == "a, b and c"

    def test_an_empty_list_joins_to_nothing(self) -> None:
        assert _join_names([]) == ""
