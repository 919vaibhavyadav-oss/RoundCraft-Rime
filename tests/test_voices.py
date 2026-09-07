"""Voice identity: the panel only works if the interviewers sound different."""

from app.panel.voices import FALLBACK, VOICE_PROFILES, verify_speakers, voice_for


def test_every_interviewer_has_their_own_speaker() -> None:
    """The compromise we are here to remove: no two panelists sharing a voice."""
    speakers = [profile.speaker for profile in VOICE_PROFILES.values()]

    assert len(set(speakers)) == len(speakers)


def test_an_unknown_panelist_falls_back_rather_than_failing_a_turn() -> None:
    assert voice_for("nobody") == FALLBACK


def test_options_carry_speaker_and_pace() -> None:
    options = voice_for("analytics").as_options()

    assert options["speaker"] == "astra"
    assert isinstance(options["speed_alpha"], float)


def test_verify_speakers_reports_anything_missing_from_the_live_catalogue() -> None:
    """The rules forbid shipping a stale speaker list, so this runs before the demo."""
    complete = {profile.speaker for profile in (*VOICE_PROFILES.values(), FALLBACK)}

    assert verify_speakers(complete) == []
    assert verify_speakers(complete - {"astra"}) == ["astra"]
