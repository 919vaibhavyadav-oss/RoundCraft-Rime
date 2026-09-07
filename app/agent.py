"""The LiveKit agent: one voice session carrying three interviewers.

This module is deliberately thin. Everything that can be decided without a
network -- who speaks next, which voice they speak in, what counts as heard
after an interruption -- lives in `app.panel` and is unit-tested there. What
remains here is wiring, which can only be proven by running it.

The shape of a turn:

    candidate speaks
      -> Deepgram transcribes
      -> the director scores the panel and picks one interviewer
      -> Rime's speaker is switched to that interviewer, per turn
      -> the language model writes their question
      -> Rime speaks it, reporting word timestamps as it goes

and on a barge-in, the floor guard fences everything belonging to the abandoned
turn so it can never arrive late in the next interviewer's voice.

The live session drives the *same* `InterviewSession` object the acceptance
tests drive. That is deliberate: a parallel reimplementation here would mean the
tested behaviour and the shipped behaviour are two different things, which is
the exact shape of the configuration drift that cost us a week on the other
build.
"""

import logging

from dotenv import load_dotenv

# LiveKit's worker reads LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET from
# the process environment rather than through our Settings object, and the
# plugins do the same for their own vendor keys. Loading .env here, before the
# CLI starts, is what makes a local run work without exporting six variables by
# hand. In deployment the environment already carries them and this is a no-op.
load_dotenv()

from collections.abc import AsyncGenerator, AsyncIterable  # noqa: E402

from livekit import agents  # noqa: E402
from livekit.agents import (  # noqa: E402
    NOT_GIVEN,
    Agent,
    AgentSession,
    ChatContext,
    ChatMessage,
    ModelSettings,
    SpeechCreatedEvent,
    StopResponse,
)
from livekit.agents.voice.io import TimedString  # noqa: E402
from livekit.plugins import deepgram, openai, rime, silero  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.panel import director  # noqa: E402
from app.panel.floor import word_from_timing  # noqa: E402
from app.panel.roster import PANEL, opening_line  # noqa: E402
from app.panel.session import InterviewSession  # noqa: E402
from app.panel.voices import DEFAULT_LANG, DEFAULT_MODEL, voice_for  # noqa: E402

logger = logging.getLogger("roundcraft")

PANEL_BRIEF = "\n".join(f"- {member.name}, {member.role}: {member.brief}" for member in PANEL)

SYSTEM_PROMPT = f"""You are one interviewer on a panel of three conducting a live
mock interview. The panel is:

{PANEL_BRIEF}

You will be told which interviewer you are speaking as, and what this turn is
for. Speak only as that person. Ask one question, in one or two sentences, and
stop. Never narrate the panel, never mention that you are an AI, and never
answer your own question.
"""


def turn_instruction(decision: director.Decision) -> str:
    """What this one interviewer is trying to get at, this turn."""
    return (
        f"Speak now as {decision.speaker.name}, the {decision.speaker.role}. "
        f"Objective ({decision.action}): {decision.objective}"
    )


class PanelAgent(Agent):
    """Binds the tested panel logic to LiveKit's turn and playback events."""

    def __init__(self) -> None:
        super().__init__(instructions=SYSTEM_PROMPT)
        self.interview = InterviewSession()

    # -- opening -------------------------------------------------------------

    async def on_enter(self) -> None:
        """Open the interview rather than waiting to be spoken to.

        A panel that joins in silence reads as broken. The hiring manager opens,
        in their own voice, and the floor is taken in their name so the very
        first sentence is interruptible on the same terms as every later one.

        Spoken rather than generated. Asking the model for this turn sends a
        request carrying only system messages, and the chat template rejects
        that outright with "No user query found in messages" - there is no
        candidate turn yet for it to answer. A fixed greeting also means every
        take of the demo opens identically, and costs nothing.
        """
        decision = self.interview.panel_opened()
        self._switch_voice(decision.speaker.id)
        logger.info(
            "floor -> %s (gen %s): opening",
            decision.speaker.name,
            self.interview.generation,
        )
        self.session.say(opening_line())

    # -- the candidate's turn ------------------------------------------------

    async def on_user_turn_completed(self, turn_ctx: ChatContext, new_message: ChatMessage) -> None:
        """Pick the next interviewer, in their voice, before the model writes.

        By the time this runs, a barge-in has already happened physically:
        LiveKit stopped playback when the candidate started speaking. So the
        first thing to settle is the turn that was cut off, and only then does
        the director get to choose who answers.
        """
        if self.interview.current_speaker is not None:
            self._close_interrupted_turn()

        answer = (new_message.text_content or "").strip()
        if not answer:
            # Deepgram produced nothing usable. Say nothing rather than let the
            # director score an empty string and pick a speaker by tie-break.
            raise StopResponse

        decision = self.interview.candidate_said(answer)
        self._switch_voice(decision.speaker.id)
        logger.info(
            "floor -> %s (gen %s): %s",
            decision.speaker.name,
            self.interview.generation,
            decision.rationale,
        )
        # The system prompt establishes the panel; this establishes which member
        # of it is speaking right now. It is added per turn rather than kept in
        # the context, so the model never holds two conflicting identities.
        turn_ctx.add_message(role="system", content=turn_instruction(decision))

    # -- what the candidate actually heard -----------------------------------

    async def transcription_node(
        self, text: AsyncIterable[str | TimedString], model_settings: ModelSettings
    ) -> AsyncGenerator[str | TimedString, None]:
        """Record each word at the moment it reaches the candidate.

        This node sits after audio synchronisation, so a word arrives here only
        once it has been played. That is what makes the transcript a record of
        what was heard rather than what was generated: when the candidate cuts
        in, this stream simply stops, and the words that never arrived are
        exactly the words that were never spoken.
        """
        generation = self.interview.generation
        async for delta in text:
            if isinstance(delta, TimedString):
                word = word_from_timing(str(delta), delta.start_time, delta.end_time)
                if word is not None:
                    self.interview.interviewer_spoke(generation, [word])
            yield delta

    # -- committing a turn ---------------------------------------------------

    def watch_speech(self, event: SpeechCreatedEvent) -> None:
        """Commit an interviewer's turn once it has finished playing out.

        Bound to the session's `speech_created` event in `entrypoint`. The
        generation is captured now, while this speech is the current turn, so a
        handle that completes late is judged against the turn it belonged to
        rather than against whatever is happening by then.
        """
        generation = self.interview.generation

        def committed(done: object) -> None:
            handle = done
            if getattr(handle, "interrupted", False):
                # Not necessarily a barge-in. A handle also reports interrupted
                # when it was generated speculatively and thrown away, or when
                # LiveKit later judges the interruption false and resumes. The
                # truthful signal is the floor still being held when the
                # candidate's turn commits, so truncation lives there.
                logger.debug("speech handle discarded at gen %s", generation)
                return
            spoken = " ".join(
                item.text_content
                for item in getattr(handle, "chat_items", [])
                if isinstance(item, ChatMessage) and item.role == "assistant" and item.text_content
            ).strip()
            if spoken and self.interview.interviewer_finished(generation, spoken):
                logger.info("committed gen %s: %s", generation, spoken)

        event.speech_handle.add_done_callback(committed)

    # -- internals -----------------------------------------------------------

    def _close_interrupted_turn(self) -> None:
        """Truncate the turn in progress to the words that were played."""
        # Every word this turn played arrived through `transcription_node`, so
        # cutting just past the last of them keeps exactly what was heard. There
        # is nothing to estimate here: the stream itself is the evidence.
        cut = self.interview.candidate_interrupted(at_ms=self.interview.heard_ms() + 1)
        if cut is None:
            return
        logger.info(
            "interrupted %s at %sms; heard %r, dropped %r",
            cut.panelist_id,
            cut.at_ms,
            cut.heard,
            cut.unheard,
        )

    def _switch_voice(self, panelist_id: str) -> None:
        """Point Rime at this interviewer's voice for the turn about to be spoken.

        Rime takes the speaker as a per-request parameter, so a handover costs
        one option update rather than a second synthesiser. This is the whole
        reason a panel can share a single voice session.
        """
        tts = self.session.tts
        if not isinstance(tts, rime.TTS):
            # Only Rime takes the speaker per request. Anything else keeps the
            # voice it was built with rather than failing the turn.
            return
        profile = voice_for(panelist_id)
        tts.update_options(speaker=profile.speaker, speed_alpha=profile.speed_alpha)


def build_session(settings: object | None = None) -> AgentSession[None]:
    """Assemble the voice pipeline.

    Rime is the primary spoken output: every word the candidate hears comes from
    it. The initial speaker is the first interviewer's; it is switched per turn
    through the plugin's update_options.
    """
    config = get_settings()
    del settings
    opening = voice_for(PANEL[0].id)
    return AgentSession[None](
        stt=deepgram.STT(model=config.deepgram_model),
        llm=openai.LLM(
            model=config.llm_model,
            base_url=config.llm_base_url or NOT_GIVEN,
            api_key=config.llm_api_key or NOT_GIVEN,
        ),
        tts=rime.TTS(
            model=config.rime_model or DEFAULT_MODEL,
            speaker=opening.speaker,
            lang=config.rime_lang or DEFAULT_LANG,
            speed_alpha=opening.speed_alpha,
            sample_rate=config.rime_sample_rate,
            # Word-level alignment is only available on the websocket transport,
            # and word-level alignment is what places an interruption exactly.
            use_websocket=config.rime_use_websocket,
        ),
        vad=silero.VAD.load(),
        # Preemptive generation fires an LLM call on every partial transcript
        # and discards it if the candidate keeps talking - up to three per turn
        # by default. A first live session showed it generating full interview
        # questions from fragments like "on MX", so each answer cost four calls
        # rather than one. We are on a free tier, and an interviewer who thinks
        # for a moment before speaking is not a defect in this product.
        turn_handling={"preemptive_generation": {"enabled": False}},
    )


async def entrypoint(ctx: agents.JobContext) -> None:
    config = get_settings()
    missing = config.missing()
    if missing:
        # Fail loudly at startup rather than halfway through an interview.
        raise RuntimeError(f"Missing required configuration: {', '.join(missing)}")

    if not config.rime_use_websocket:
        logger.warning(
            "RIME_USE_WEBSOCKET is off, so words carry no start times and an "
            "interruption is placed by playback pacing alone."
        )

    agent = PanelAgent()
    session = build_session()
    session.on("speech_created", agent.watch_speech)

    await session.start(room=ctx.room, agent=agent)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
