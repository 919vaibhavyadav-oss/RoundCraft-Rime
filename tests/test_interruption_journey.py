"""The claim, end to end.

RIME_EVIDENCE.md states that when a candidate interrupts one interviewer and
another takes the floor:

  - queued Rime audio stops                        (LiveKit, measured live)
  - the abandoned response is never spoken         (here)
  - the transcript holds only what was heard       (here)
  - the next interviewer is chosen from that text  (here)
  - a barge-in during silence creates no turn      (here)

These run a whole scripted interview rather than poking one function, because
the failure this guards against is an interaction between three components that
are each individually correct.
"""

from app.panel.floor import SpokenWord
from app.panel.session import InterviewSession


def spoken(*pairs: tuple[str, int]) -> list[SpokenWord]:
    return [SpokenWord(text=text, start_ms=start) for text, start in pairs]


QUESTION = spoken(
    ("What", 0),
    ("tradeoff", 150),
    ("did", 400),
    ("you", 520),
    ("accept", 640),
    ("when", 900),
    ("you", 1000),
    ("cut", 1100),
    ("scope", 1250),
)


def test_an_uninterrupted_interview_records_every_turn() -> None:
    session = InterviewSession()

    decision = session.candidate_said("We measured retention at 22 percent.")
    session.interviewer_spoke(session.generation, QUESTION)
    counted = session.interviewer_finished(session.generation, "What tradeoff did you accept?")

    assert counted is True
    assert [turn.speaker_id for turn in session.transcript] == ["candidate", decision.speaker.id]
    assert session.state.question_counts[decision.speaker.id] == 1


def test_the_transcript_holds_only_what_the_candidate_heard() -> None:
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    session.interviewer_spoke(session.generation, QUESTION)

    session.candidate_interrupted(at_ms=700)

    interviewer_turn = session.transcript[-1]
    assert interviewer_turn.interrupted is True
    # "accept" begins at 640ms, so the candidate heard it before cutting in at 700ms.
    assert interviewer_turn.text == "What tradeoff did you accept"
    assert "cut scope" not in session.heard_text()


def test_the_abandoned_answer_cannot_be_committed_afterwards() -> None:
    """The model returns the full question, too late. It must not land."""
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    stale = session.generation
    session.interviewer_spoke(stale, QUESTION)
    session.candidate_interrupted(at_ms=700)

    counted = session.interviewer_finished(stale, "What tradeoff did you accept when you cut scope?")

    assert counted is False
    assert "cut scope" not in session.heard_text()


def test_the_abandoned_answer_cannot_land_in_the_next_interviewers_voice() -> None:
    """The failure this whole feature exists to prevent."""
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    stale = session.generation
    session.interviewer_spoke(stale, QUESTION)
    session.candidate_interrupted(at_ms=700)

    # A different interviewer takes over.
    session.candidate_said("Sorry, let me talk about the customer problem instead.")
    fresh_speaker = session.current_speaker
    assert fresh_speaker is not None

    # The old answer finally arrives.
    leaked = session.interviewer_finished(stale, "What tradeoff did you accept when you cut scope?")

    assert leaked is False
    assert all(turn.text != "What tradeoff did you accept when you cut scope?" for turn in session.transcript)


def test_the_next_interviewer_is_chosen_from_the_truncated_answer() -> None:
    """The director must react to the conversation that happened, not the intended one."""
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    session.interviewer_spoke(session.generation, QUESTION)
    session.candidate_interrupted(at_ms=700)

    decision = session.candidate_said("Actually the customer problem was onboarding.")

    assert decision.speaker.id == "product-sense"


def test_a_barge_in_during_silence_creates_no_turn() -> None:
    session = InterviewSession()

    assert session.candidate_interrupted(at_ms=500) is None
    assert session.transcript == []


def test_an_interviewer_cut_off_before_a_word_played_leaves_no_turn() -> None:
    """They were selected, but the candidate heard nothing. Nothing is recorded."""
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    session.interviewer_spoke(session.generation, QUESTION)

    session.candidate_interrupted(at_ms=0)

    assert [turn.speaker_id for turn in session.transcript] == ["candidate"]
    assert session.state.question_counts == {}


def test_an_interruption_still_counts_the_interviewer_who_was_heard() -> None:
    """They did speak, and the candidate is responding to it, so it counts."""
    session = InterviewSession()
    decision = session.candidate_said("We measured retention at 22 percent.")
    session.interviewer_spoke(session.generation, QUESTION)

    session.candidate_interrupted(at_ms=700)

    assert session.state.question_counts[decision.speaker.id] == 1


def test_a_long_interview_with_interruptions_stays_consistent() -> None:
    """The transcript must always alternate candidate, interviewer, candidate."""
    session = InterviewSession()
    answers = [
        "We measured retention at 22 percent.",
        "The customer problem was onboarding.",
        "I led the team through that migration.",
        "Because the metric moved with activation.",
    ]

    for index, answer in enumerate(answers):
        session.candidate_said(answer)
        session.interviewer_spoke(session.generation, QUESTION)
        if index % 2 == 0:
            session.candidate_interrupted(at_ms=700)
        else:
            session.interviewer_finished(session.generation, "What tradeoff did you accept?")

    speakers = [turn.speaker_id for turn in session.transcript]
    for first, second in zip(speakers, speakers[1:], strict=False):
        assert not (first == "candidate" and second == "candidate"), (
            "two candidate turns in a row means an interviewer turn was lost"
        )
    assert sum(1 for turn in session.transcript if turn.by_candidate) == len(answers)


def test_no_turn_is_ever_recorded_twice() -> None:
    session = InterviewSession()
    session.candidate_said("We measured retention at 22 percent.")
    generation = session.generation
    session.interviewer_spoke(generation, QUESTION)

    assert session.interviewer_finished(generation, "What tradeoff did you accept?") is True
    assert session.interviewer_finished(generation, "What tradeoff did you accept?") is False
    assert len(session.transcript) == 2
