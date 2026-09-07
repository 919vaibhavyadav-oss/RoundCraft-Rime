"""Which Rime voice each interviewer speaks in.

The panel's whole premise is that several interviewers share one voice session
and stay individually recognisable. Our previous text-to-speech vendor offered
three timbres for five people, so two interviewers shared a voice ID and were
separated only by pitch and pace. Rime's Coda catalogue removes that compromise:
the speaker is a per-request parameter, so each interviewer simply has their own.

Speaker names here are placeholders until the live catalogue is checked at
submission time. The event rules forbid shipping a stale speaker list, so
`verify_speakers` exists to be run against the catalogue before the demo.
"""

from dataclasses import dataclass

# Rime exposes delivery controls alongside the voice. Keeping a small,
# deliberate spread of pace makes an audio-only panel easier to follow than
# voice identity alone does.
DEFAULT_MODEL = "coda"
DEFAULT_LANG = "eng"


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    """One interviewer's Rime configuration."""

    speaker: str
    speed_alpha: float

    def as_options(self) -> dict[str, object]:
        """The keyword arguments handed to the Rime plugin for this turn."""
        return {"speaker": self.speaker, "speed_alpha": self.speed_alpha}


# Chosen from the live Coda catalogue for maximum separation, because a panel
# whose members sound alike is the failure this product exists to avoid. The
# spread is deliberate: an older female, a younger male, a younger female, at
# three different paces. speed_alpha below 1.0 is slower than Rime's default.
VOICE_PROFILES: dict[str, VoiceProfile] = {
    # Elder, clear and professional. The person running the room.
    "hiring-manager": VoiceProfile(speaker="argon", speed_alpha=0.95),
    # Young adult male, warm and low. Approachable enough to probe with.
    "product-sense": VoiceProfile(speaker="arcade", speed_alpha=1.0),
    # Young adult female, bright and quick. The one who challenges a number.
    "analytics": VoiceProfile(speaker="astra", speed_alpha=1.05),
}

FALLBACK = VoiceProfile(speaker="argon", speed_alpha=1.0)


def voice_for(panelist_id: str) -> VoiceProfile:
    """Resolve an interviewer's voice, never failing a live turn over a lookup."""
    return VOICE_PROFILES.get(panelist_id, FALLBACK)


def verify_speakers(catalogue: set[str]) -> list[str]:
    """Return any configured speaker missing from the live Rime catalogue.

    The event rules require the current catalogue at submission time rather than
    a list copied into the application months earlier, so this runs in CI and
    before recording the demo.
    """
    return sorted(
        {profile.speaker for profile in (*VOICE_PROFILES.values(), FALLBACK)} - catalogue
    )
