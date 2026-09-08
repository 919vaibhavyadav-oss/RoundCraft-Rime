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
| Endpoint | `wss://users-ws.rime.ai` (streaming). The HTTP path `https://users.rime.ai/v1/rime-tts` is not used in the demo |
| Region | Rime global endpoint; LiveKit Cloud project region `India South` |
| Audio format | PCM, 16-bit mono |
| Sample rate | 48000 Hz, matching LiveKit's room audio so nothing is resampled |
| Transport | Rime websocket streaming (`use_websocket=True`), carried to the browser over LiveKit WebRTC |
| Framework | `livekit-agents` 1.8.0 with `livekit-plugins-rime` 1.8.0 |
| Aligned transcript | Enabled. Requires **both** `use_websocket=True` and `AgentSession(use_tts_aligned_transcript=True)` |

Speaker is set per turn through the plugin's `update_options`, which is what
lets one session carry several interviewers on a single Rime connection.

Rime is the only speech output. There is no fallback provider, so if Rime is
unavailable the session surfaces the failure rather than substituting another
voice. The active provider is therefore unambiguous throughout the demo.

> Placeholders above are pinned in `app/panel/voices.py` and checked against the
> live Rime catalogue by `verify_speakers` before each demo recording.

## Try it

| | |
| --- | --- |
| Live application | <https://roundcraft-rime-web.onrender.com> |
| Access code | `panel-2026` |

The code gates the one endpoint that starts an interview, because starting one
spends real credit at Rime, Deepgram and the model provider. It is a quota gate
rather than a secret, which is why it can be written down here; no data sits
behind it, and the server refuses to serve a public instance without one.

## Running the demo

Two terminals. The agent, which waits for a room:

```bash
uv run python -m app.agent dev
```

and the candidate's interface, which serves the page and mints its join token:

```bash
uv run python scripts/serve_web.py
```

Then open <http://localhost:8080> and click Join.

[DEMO_SCRIPT.md](DEMO_SCRIPT.md) is the four-minute run that exercises every
clause of the claim, including which sentence to say so the benchmark lookup
has something to find, and when to cut across it.

The LiveKit API secret stays in the server process. The browser receives only a
short-lived token scoped to one room, which is what keeps credentials out of
client code.

## Architecture

```
browser ──WebRTC──> LiveKit ──> Deepgram STT
                                     │
                              Panel Director  (scores the panel, picks one speaker)
                                     │
                              language model  (writes that interviewer's question)
                                     │        └─> check_benchmark  (a deliberate
                                     │            delay, so there is work in
                                     │            flight to interrupt)
                                     │
                                Rime TTS  ──> LiveKit ──> browser
```

The floor guard (`app/panel/floor.py`) sits across the whole loop, fencing work
that belongs to an interrupted turn.

The page is not a passive viewer. The agent broadcasts each decision it makes
over the LiveKit data channel (`app/panel/events.py`), so an interruption is
visible as it happens: the words the candidate heard stay, and the words that
were never spoken appear struck through beside them. The claim this project
rests on should be watchable by the person it happens to, not reconstructed
afterwards from a log.

### The candidate's background

The landing page asks for a CV, optionally. If one is given it is sent over the
LiveKit data channel after joining, never in the join token or a URL, and the
panel is told to ask about the work it names rather than in general terms.

It is personal data and is handled narrowly: held in the agent process for one
session, never written to disk, never logged (only its length is), and email
addresses, phone numbers and links are stripped before it reaches the model.
`app/panel/background.py` is pure and `tests/test_background.py` asserts all of
that, including that a year range like "2021 - 2024" survives redaction — an
earlier version deleted it as a phone number, which would have removed exactly
the career timeline an interviewer wants to ask about.

A candidate who skips the field gets an identical interview, asked in general
terms.

## Third-party services

- **Rime** — text to speech, the primary spoken output
- **LiveKit** — realtime transport, turn handling, barge-in
- **Deepgram** — speech recognition
- An OpenAI-compatible language model for interviewer questions

The panel has one tool, `check_benchmark`, which looks up the industry range
for a metric the candidate cited. It waits `LOOKUP_DELAY_SECONDS` on purpose:
the event brief asks for a fixed delay in a tool call so that a candidate can
interrupt work that is genuinely in flight. A lookup whose turn has been
interrupted is discarded rather than spoken as current.

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

## Deploying

`render.yaml` declares two services from one image. The agent is a worker: it
dials out to LiveKit and serves no inbound traffic, so it has no URL. The
interface is a web service that serves the page and mints the join token.

The split matters. Only the web service holds `LIVEKIT_API_SECRET`, and only to
sign a short-lived token scoped to one room. The Rime, Deepgram and model
credentials live on the worker alone and never reach anything the browser talks
to.

Set `ACCESS_CODE` before exposing it. Minting a token starts an interview, and
an interview spends money at Rime, Deepgram and the model provider, so that one
endpoint is gated: the code is compared in constant time, checked on the server,
sent by POST so it never reaches a URL a proxy would log, and rate limited to a
dozen attempts per address per five minutes. The server refuses to start a
public instance without one.

It is not an account system and does not pretend to be. There are no passwords
and no stored personal data; the name is a display label, stripped to letters,
digits and basic punctuation.

1. On Render, **New → Blueprint**, point it at this repository.
2. Set the eight worker secrets, the three web secrets, and `ACCESS_CODE` on
   the web service, in the dashboard.
   Nothing is committed, and the non-secret values are pinned in `render.yaml`
   so a deployment cannot quietly differ from the demo.
3. Open the web service's URL and start an interview.

The worker must be running for anything to happen: with it stopped, a candidate
joins a room that nobody else is in.

## Known limitations and failure behaviour

- If Rime is unavailable the session surfaces the failure rather than silently
  falling back to another voice provider. Any fallback added later will be
  disclosed here and made observable in the demo, per the event rules.
- The floor guard is pure logic covering what the application *chooses* to play;
  playback stop latency belongs to LiveKit and is measured in the evidence file.
- Word-level cut points need two settings, not one: `RIME_USE_WEBSOCKET` so Rime
  sends per-word offsets, and `use_tts_aligned_transcript` so LiveKit delivers
  them. The second defaults to off and fails silently, so the agent logs the
  audio each turn timed and warns on zero.
- Tested with three interviewers.
- The sample rate is not a preference. At 22050 Hz the pipeline resamples every
  frame, and soxr asserts `LSX_FFT_BR == NULL` and aborts the process mid-call.
  48000 Hz matches the room and removes the resampler from the speech path.

## Status

The panel runs live. A session dispatches to the worker, the hiring manager
opens in her own Rime voice, the director picks each next interviewer from what
the candidate actually said, and the voice switches per turn on one Rime
connection. 77 tests pass, 43 of them covering the interruption claim.

Three defects found by running it, each fixed and each now covered:

| Found | Cause |
| --- | --- |
| Every turn cost four model calls | Preemptive generation writing questions from partial transcripts |
| Turns timed 0ms of audio | `use_tts_aligned_transcript` defaults off, discarding Rime's alignment |
| A 13.5s greeting timed 5.1s | Rime's offsets restart per synthesis request, one per sentence |

None of them could fail a unit test: the tests were right about the code and
wrong about the world. What caught the last two was a runtime assertion that
reports how many milliseconds of audio each turn actually played, and warns on
zero. It is deliberately still in the code.

Outstanding: the live barge-in measurements in `RIME_EVIDENCE.md`, which need a
recorded session rather than more code.
