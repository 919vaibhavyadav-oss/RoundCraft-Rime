# Demo script

Four minutes, one take. Covers every clause of the claim in
[RIME_EVIDENCE.md](RIME_EVIDENCE.md) and every item the event brief requires a
demo to show.

Read the **bold** lines aloud. Everything else is what should happen.

---

## Before you press record

- [ ] Agent running: `uv run python -m app.agent dev` — wait for `registered worker`
- [ ] Interface running: `uv run python scripts/serve_web.py`
- [ ] **Suspend the Render worker** (dashboard → `roundcraft-rime-agent` → Settings →
      Suspend). Two workers are registered and each take is a coin toss between
      them. Resume it after filming so judges can reach it.
- [ ] <http://localhost:8080> open, three interviewers showing
- [ ] One terminal open for the test run at the end. Nothing else needs it:
      the interface shows the cut, the milliseconds and the audio played.
- [ ] **No `.env`, no dashboard with a key, nothing showing a credential.** The
      rules name recordings explicitly: an exposed credential is an eligibility
      failure, not a deduction.
- [ ] Headphones on, so the panel's voice does not reach your microphone

---

## 0:00 — Who this is for

> **"Anyone preparing for an interview can rehearse questions. Nobody can
> rehearse a panel — three interviewers who talk over you, hand off to each
> other, and follow up on the number you just said. That's what this is."**

> **"Every voice you hear is Rime. There is no fallback, so if Rime is down this
> product is silent. Three interviewers, three Rime speakers, one connection,
> switched per turn."**

Point at the three cards: Maya `argon`, Noah `arcade`, Priya `astra`.

*Covers: target user and problem; which speech provider is active.*

---

## 0:30 — Join

Type your name, the access code, and **paste two or three lines of your CV**.

> **"It asks for a background so the panel interviews me, not a generic
> candidate. It is held for this session only, never saved, and contact details
> are stripped before the panel sees it."**

Click **Join the interview**. Maya opens, unprompted, in her own voice.

*Covers: normal end-to-end flow.*

---

## 1:00 — Answer, and let it hand off

Answer her question in two or three sentences, naming something real from your
CV and **a metric with a number**:

> **"I shipped Compass for premium card members. Retention moved four percent
> after we rebuilt onboarding."**

A different interviewer takes over in a different voice, and asks about *your*
project. Point at the italic line under the tiles:

> **"It didn't take turns. It chose Noah because the answer moved onto product
> sense ground, and it says so."**

*Covers: the working product, and Rime's role in it.*

---

## 1:45 — The stress case

**While that interviewer is five or six words into their next question, talk
straight over them.**

> **"Sorry — I meant activation, not retention."**

Not before they start, and not after the full stop. Mid-sentence is the point.

*Covers: the deliberate stress case.*

---

## 2:15 — What just happened, on screen

Point at the red turn:

> **"The words I actually heard are in black. The struck-through words are the
> rest of the sentence — generated, and never spoken. They are not in the
> transcript, because this product assesses you from a transcript, and a
> sentence you never heard must never become evidence about you."**

Then the cut marker:

> **"Cut at four thousand milliseconds. Not an estimate — Rime reports a
> timestamp per word, so we know exactly which word I heard last."**

If a benchmark lookup was running:

> **"And the lookup was still in flight when I changed the question. It came
> back, and it was discarded rather than spoken by whoever took over."**

*Covers: the hard voice problem, and the result.*

---

## 2:50 — End the interview

Click **End interview**. The session record appears.

> **"Everything the panel heard, and struck through, everything it started and
> I stopped. Nothing I did not hear can be used as evidence about me."**

*A strong closing frame: the claim, stated where the candidate reads it.*

---

## 3:15 — The measurement

Stay on the session record. Point at the millisecond stamps under each turn.

> **"Every turn reports how many milliseconds of audio actually played. If that
> ever reads zero the word timings are gone and the cut point is guesswork, so
> the agent warns. That check caught three real bugs during this build."**

Then switch to a terminal and run:

```bash
uv run pytest -q
```

> **"A hundred and twenty-seven tests. The acceptance test was written before
> the implementation, and the interruption claim has fifty-three of them."**

*Covers: evidence and reproducibility.*

---

## 3:45 — Close

> **"The hard part isn't stopping the audio. It's that interrupting a panel
> means someone else takes over, so the half-spoken sentence and any tool result
> still in flight have to be fenced — or you hear one interviewer's words in
> another's voice. That's the generation fence in floor.py, and that's what
> those tests prove."**

---

## If it goes wrong mid-take

| What you see | What to do |
| --- | --- |
| Nobody speaks after joining | Check the terminal says `registered worker`. Rejoin. |
| Your words are not transcribed | Watch the level bar on your own tile. If it does not move, change device in the dropdown at the bottom of the call. |
| `heard ''` on the interruption | You cut in before any audio played. Let them get five or six words out. |
| `nothing was dropped` | You waited for the full stop. Cut in earlier. |
| The lookup finds no benchmark | Your line had no metric word. Say retention, activation, conversion, engagement or churn, with a number. |

---

## Optional: more of the lookup

Each returns a different band, all with the same interruptible delay:

| Say | Returns |
| --- | --- |
| "retention went up four percent" | typical 2–3% per quarter, strong above 5% |
| "activation is at thirty percent" | typical 30–40% of signups, strong above 55% |
| "conversion sits around two percent" | typical 2–4% of visitors, strong above 8% |
| "our DAU to MAU ratio is twenty percent" | typical near 20%, strong above 35% |
| "churn is about five percent monthly" | typical 4–6% self-serve, strong below 2% |

A metric outside that list is answered honestly: the interviewer says no
benchmark is available and asks how it was measured, rather than inventing one.
