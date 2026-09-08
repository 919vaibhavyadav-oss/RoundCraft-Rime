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

import asyncio
import json
import logging
from typing import TYPE_CHECKING, cast

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
    RunContext,
    SpeechCreatedEvent,
    StopResponse,
    function_tool,
)
from livekit.agents.voice.io import TimedString  # noqa: E402
from livekit.plugins import deepgram, openai, rime, silero  # noqa: E402

from app.config import get_settings  # noqa: E402

if TYPE_CHECKING:
    from openai.types import ReasoningEffort
from app.panel import director, events  # noqa: E402
from app.panel.benchmarks import find_benchmark  # noqa: E402
from app.panel.floor import WordTimeline  # noqa: E402
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
        # Set once the job starts. The interview does not depend on it: if the
        # browser is not listening, or publishing fails, nothing here changes.
        self.room: object | None = None

    def announce(self, event: dict[str, object]) -> None:
        """Tell the room what the panel just did, without ever blocking it."""
        try:
            # local_participant is a property that raises before the room is
            # connected rather than being absent, so getattr's default never
            # applies and this has to be a real try.
            publish = self.room.local_participant.publish_data  # type: ignore[union-attr]
        except Exception:
            return
        task = asyncio.create_task(
            publish(json.dumps(event), topic=events.TOPIC, reliable=True)
        )
        # A dropped frame in the UI must never surface as a failed interview.
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

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
        self.announce(events.roster())
        self.announce(
            events.floor_taken(
                decision.speaker.id,
                decision.speaker.name,
                self.interview.generation,
                decision.rationale,
            )
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
        self.announce(events.candidate_said(answer))
        self.announce(
            events.floor_taken(
                decision.speaker.id,
                decision.speaker.name,
                self.interview.generation,
                decision.rationale,
            )
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
        # One timeline per turn: Rime's offsets restart at every sentence, and
        # this is what puts them back on a single clock.
        timeline = WordTimeline()
        async for delta in text:
            if isinstance(delta, TimedString):
                word = timeline.place(str(delta), delta.start_time, delta.end_time)
                if word is not None:
                    self.interview.interviewer_spoke(generation, [word])
            yield delta

    # -- work the candidate can interrupt ------------------------------------

    @function_tool
    async def check_benchmark(self, context: RunContext[None], claim: str) -> str:
        """Look up the industry benchmark for a metric the candidate just cited.

        Use this whenever the candidate gives a number for one of: retention,
        activation, conversion, engagement, churn. Pass their claim in their
        own words. A test keeps this list in step with the benchmark data.
        """
        # Captured before the wait, so a result arriving after a handover is
        # judged against the turn that asked for it rather than whichever turn
        # happens to be running by the time it returns.
        generation = self.interview.generation
        logger.info("lookup started for %r at gen %s", claim, generation)
        self.announce(events.lookup_started(claim, generation))

        # A fixed delay, as the brief's proof procedure requires, so there is a
        # real window in which the candidate can cut across work in flight.
        await asyncio.sleep(get_settings().lookup_delay_seconds)

        if not self.interview.floor.accepts(generation):
            # The candidate interrupted while this ran. The answer belongs to a
            # question they abandoned, so it must not be spoken as current, and
            # must not reach the model as context either.
            logger.info("discarded stale lookup of %r from gen %s", claim, generation)
            self.announce(events.lookup_discarded(claim, generation))
            raise StopResponse

        benchmark = find_benchmark(claim)
        if benchmark is None:
            logger.info("no benchmark for %r", claim)
            return (
                "No benchmark is available for that metric. Say so plainly and ask "
                "how they measured it instead of quoting a number."
            )
        logger.info("lookup returned %s for gen %s", benchmark.metric, generation)
        self.announce(events.lookup_returned(benchmark.metric, generation))
        return benchmark.spoken()

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
            spoken = " ".join(
                item.text_content
                for item in getattr(handle, "chat_items", [])
                if isinstance(item, ChatMessage) and item.role == "assistant" and item.text_content
            ).strip()
            if getattr(handle, "interrupted", False):
                # The candidate cut across this. Truncate here rather than
                # later, because this is the only place the sentence the
                # interviewer *meant* to say is still available, and the words
                # that never played are otherwise unrepresentable: the timing
                # stream only ever reports a word once it has been heard.
                if self.interview.floor.accepts(generation):
                    self._close_interrupted_turn(intended=spoken)
                else:
                    logger.debug("speech handle discarded at gen %s", generation)
                return

            heard_ms = self.interview.heard_ms()
            if spoken and self.interview.interviewer_finished(generation, spoken):
                logger.info(
                    "committed gen %s after %sms of audio: %s", generation, heard_ms, spoken
                )
                self.announce(
                    events.turn_committed(
                        self.interview.transcript[-1].speaker_id, generation, spoken, heard_ms
                    )
                )
                if heard_ms == 0:
                    # Rime reported no word timings, so an interruption during
                    # this turn could not have been placed. Worth knowing.
                    logger.warning(
                        "no word timings for gen %s; needs RIME_USE_WEBSOCKET and "
                        "use_tts_aligned_transcript",
                        generation,
                    )

        event.speech_handle.add_done_callback(committed)

    # -- internals -----------------------------------------------------------

    def _close_interrupted_turn(self, intended: str | None = None) -> None:
        """Truncate the turn in progress to the words that were played."""
        # Every word this turn played arrived through `transcription_node`, so
        # cutting just past the last of them keeps exactly what was heard. There
        # is nothing to estimate here: the stream itself is the evidence.
        cut = self.interview.candidate_interrupted(
            at_ms=self.interview.heard_ms() + 1, intended=intended
        )
        if cut is None:
            return
        logger.info(
            "interrupted %s at %sms; heard %r, dropped %r",
            cut.panelist_id,
            cut.at_ms,
            cut.heard,
            cut.unheard,
        )
        self.announce(events.turn_interrupted(cut))

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
            max_completion_tokens=config.llm_max_tokens,
            reasoning_effort=cast("ReasoningEffort", config.llm_reasoning_effort or None),
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
        # Without this, transcription_node is handed plain strings and Rime's
        # word alignment is discarded before it ever reaches us, so an
        # interruption has no timestamps to be placed against. It is the flag
        # the entire interruption claim rests on.
        use_tts_aligned_transcript=True,
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
    agent.room = ctx.room
    session = build_session()
    session.on("speech_created", agent.watch_speech)

    await session.start(room=ctx.room, agent=agent)


if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
