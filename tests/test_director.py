"""The director hands the floor deliberately, and never on a rotation."""

from app.panel.director import PanelState, _objective, choose_next, record
from app.panel.roster import PANEL


def test_an_answer_about_metrics_goes_to_the_analyst() -> None:
    decision = choose_next(PanelState(), "We measured retention at 22 percent.")

    assert decision.speaker.id == "analytics"


def test_an_answer_about_users_goes_to_product_sense() -> None:
    decision = choose_next(PanelState(), "The customer problem was onboarding.")

    assert decision.speaker.id == "product-sense"


def test_the_same_interviewer_can_follow_up_on_a_reasoned_answer() -> None:
    """A rotation would move on here. Returning to the same person is the point."""
    state = PanelState(current_speaker_id="analytics", question_counts={"analytics": 1})

    decision = choose_next(state, "We chose it because the metric moved with activation.")

    assert decision.speaker.id == "analytics"


def test_an_interviewer_who_has_asked_a_lot_is_pushed_down() -> None:
    """Without this, one strong expertise match would monopolise the interview."""
    talkative = PanelState(question_counts={"analytics": 4})

    decision = choose_next(talkative, "We measured retention at 22 percent.")

    assert decision.speaker.id != "analytics"


def test_selection_is_deterministic_for_the_same_input() -> None:
    state = PanelState()
    first = choose_next(state, "I am not sure, roughly speaking.")
    second = choose_next(state, "I am not sure, roughly speaking.")

    assert first.speaker.id == second.speaker.id


def test_an_interviewer_opens_with_their_own_first_angle() -> None:
    """Not a generic probe. Each interviewer has a line of questioning."""
    decision = choose_next(PanelState(), "Retention measured 22 percent after launch.")

    assert decision.action == "ask"
    assert decision.objective == decision.speaker.angles[0]


def test_the_same_interviewer_never_repeats_an_angle() -> None:
    """The bug this exists to prevent: every turn asking the same question.

    Before this, an ordinary turn resolved to one of two fixed strings, so the
    panel put a variation of the same question all interview.
    """
    state = PanelState()
    speaker = None
    seen: list[str] = []
    for _ in range(4):
        decision = choose_next(state, "Retention measured 22 percent after launch.")
        if speaker is None:
            speaker = decision.speaker
        if decision.speaker.id == speaker.id:
            seen.append(decision.objective)
        state = record(state, decision)

    assert len(seen) == len(set(seen)), f"repeated an objective: {seen}"


def test_the_generic_probes_take_over_once_the_arc_is_spent() -> None:
    """A long interview must still have somewhere to go."""
    speaker = PANEL[0]
    state = PanelState(question_counts={speaker.id: len(speaker.angles)})

    unsupported = _objective(speaker, len(speaker.angles), "it went really well", False)
    supported = _objective(speaker, len(speaker.angles), "retention rose 4 percent", True)

    assert unsupported[0] == "probe"
    assert "evidence" in unsupported[1].lower()
    assert supported[0] == "challenge"
    assert "tradeoff" in supported[1].lower()
    assert state.question_counts[speaker.id] == len(speaker.angles)


def test_an_audio_check_is_answered_rather_than_interviewed() -> None:
    decision = choose_next(PanelState(), "Sorry, can you hear me?")

    assert decision.action == "clarify"
    assert "hear you" in decision.objective


def test_a_candidate_who_is_stuck_is_moved_on_rather_than_pressed() -> None:
    decision = choose_next(PanelState(), "I don't know, can we skip this one?")

    assert decision.action == "ask"
    assert "different one" in decision.objective


def test_hedging_is_named_in_the_rationale() -> None:
    decision = choose_next(PanelState(), "It was roughly fine I guess.")

    assert "hedged" in decision.rationale


def test_the_rationale_names_the_interviewer() -> None:
    decision = choose_next(PanelState(), "We measured retention at 22 percent.")

    assert decision.speaker.name in decision.rationale


def test_recording_a_turn_advances_the_state() -> None:
    state = PanelState()
    decision = choose_next(state, "We measured retention at 22 percent.")

    advanced = record(state, decision)

    assert advanced.current_speaker_id == decision.speaker.id
    assert advanced.question_counts[decision.speaker.id] == 1
    # The original is untouched, so a turn that gets interrupted leaves no trace.
    assert state.question_counts == {}


def test_the_panel_shares_the_floor_over_a_long_interview() -> None:
    """Nobody should be silent after a dozen turns of mixed material."""
    state = PanelState()
    answers = [
        "We measured retention at 22 percent.",
        "The customer problem was onboarding.",
        "I led the team through the migration.",
    ] * 4

    for answer in answers:
        state = record(state, choose_next(state, answer))

    assert len(state.question_counts) == 3
    assert all(count > 0 for count in state.question_counts.values())
