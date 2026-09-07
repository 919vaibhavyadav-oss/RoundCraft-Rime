"""The director hands the floor deliberately, and never on a rotation."""

from app.panel.director import PanelState, choose_next, record


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


def test_a_claim_without_evidence_is_probed() -> None:
    decision = choose_next(PanelState(), "It went really well for the team.")

    assert decision.action == "probe"
    assert "evidence" in decision.objective.lower()


def test_a_claim_with_evidence_is_challenged_on_the_tradeoff() -> None:
    decision = choose_next(PanelState(), "Retention measured 22 percent after launch.")

    assert decision.action == "challenge"
    assert "tradeoff" in decision.objective.lower()


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
