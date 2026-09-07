# RoundCraft on Rime

An AI interview panel that shares one voice session. Two to five interviewers
speak one at a time, each in their own Rime voice, and a silent director decides
who responds to each answer.

**Rime is the primary spoken output.** Every word the candidate hears is
synthesised by Rime.

## The hard voice problem

Interrupting a panel is harder than interrupting a bot: cutting off one
interviewer hands the floor to another, so the abandoned sentence must never
arrive late in the new speaker's voice, and the transcript must record only what
was actually heard. See [RIME_EVIDENCE.md](RIME_EVIDENCE.md) for the claim, the
acceptance test, and the results.

## Rime configuration

The exact configuration used in the demo. Verified against the live catalogue
before submission.

| Setting | Value |
| --- | --- |
| Model | `coda` |
| Speakers | `argon` (Hiring Manager), `arcade` (Product Sense), `astra` (Analytics) |
| Language | `eng` |
| Endpoint | Rime default, via the official LiveKit plugin |
| Audio format | PCM |
| Sample rate | 22050 Hz |
| Transport | LiveKit WebRTC, Rime websocket streaming (`use_websocket=True`) |

Speaker is set per turn through the plugin's `update_options`, which is what
lets one session carry several interviewers.

> Placeholders above are pinned in `app/panel/voices.py` and checked against the
> live Rime catalogue by `verify_speakers` before each demo recording.

## Architecture

```
browser ──WebRTC──> LiveKit ──> Deepgram STT
                                     │
                              Panel Director  (scores the panel, picks one speaker)
                                     │
                              language model  (writes that interviewer's question)
                                     │
                                Rime TTS  ──> LiveKit ──> browser
```

The floor guard (`app/panel/floor.py`) sits across the whole loop, fencing work
that belongs to an interrupted turn.

## Third-party services

- **Rime** — text to speech, the primary spoken output
- **LiveKit** — realtime transport, turn handling, barge-in
- **Deepgram** — speech recognition
- An OpenAI-compatible language model for interviewer questions

## Setup

```bash
uv python pin 3.12
uv sync --all-extras
uv run python scripts/setup.py
```

The last command does the rest: it creates `.env`, names every key that is
still blank and where to get it, then tests each service for real. Run it again
after filling anything in. It never prints a key value, so its output is safe to
share.

When everything passes:

```bash
uv run python -m app.agent dev
```

Then open [agents-playground.livekit.io](https://agents-playground.livekit.io),
point it at your LiveKit project, and join the room.

Credentials are read from the environment only. `.env` is gitignored,
`.env.example` holds placeholders alone, and CI fails the build if anything
key-shaped reaches the tree.

## Known limitations and failure behaviour

- If Rime is unavailable the session surfaces the failure rather than silently
  falling back to another voice provider. Any fallback added later will be
  disclosed here and made observable in the demo, per the event rules.
- The floor guard is pure logic covering what the application *chooses* to play;
  playback stop latency belongs to LiveKit and is measured in the evidence file.
- Word-level cut points require Rime websocket streaming. Without it the cut
  point degrades to elapsed-time estimation.
- Tested with three interviewers.

## Status

Phase 1 of 6. The floor guard and voice mapping are implemented and tested; the
LiveKit agent wiring is in progress.
