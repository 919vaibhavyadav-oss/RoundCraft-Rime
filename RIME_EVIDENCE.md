# Rime evidence

## The hard voice problem

**Interrupting a panel is harder than interrupting a bot.**

RoundCraft is a mock-interview room where two to five AI interviewers share one
voice session. Only one speaks at a time, and each speaks in their own Rime
voice. When the candidate cuts across whoever is speaking, a different
interviewer often takes the floor.

That makes barge-in structurally harder than it is for a single assistant, in
three ways that are properties of the whole application rather than of the
text-to-speech model:

1. **A stale sentence can arrive in the wrong voice.** The interrupted
   interviewer's answer may still be in flight at the language model. If it
   returns after the handover and is spoken, the candidate hears interviewer B
   deliver interviewer A's sentence.
2. **The transcript can record what was never heard.** Every score this product
   gives cites a transcript turn. A sentence the candidate never heard must
   never become evidence about them.
3. **The director can reason about a conversation that did not happen.** The
   next speaker is chosen from the candidate's answer. If selection reads the
   intended answer rather than the part actually delivered before the barge-in,
   it is reacting to audio nobody produced.

## The claim

When the candidate interrupts an interviewer mid-sentence:

- queued Rime audio stops, and no further audio for that turn is played
- the abandoned response is never spoken, in any voice
- a benchmark lookup still in flight is discarded rather than spoken as current
- the transcript records only the words the candidate actually heard
- the next interviewer is selected from that truncated text
- a barge-in during silence creates no turn at all

## Acceptance test

**Defined before the implementation, per the event rules.**

Run:

```bash
pytest tests/test_floor.py tests/test_interruption_journey.py tests/test_benchmarks.py -q
```

The test covers the claim clause by clause:

| Clause | Test |
| --- | --- |
| Only heard words are kept | `test_an_interrupt_keeps_only_what_was_heard` |
| The abandoned response cannot be spoken | `test_the_abandoned_response_can_no_longer_be_spoken` |
| A late result cannot pollute the new turn | `test_a_late_arriving_result_cannot_pollute_the_new_turn` |
| Silence barge-in creates nothing | `test_interrupting_silence_does_nothing` |
| Boundaries: before first word, after last | `test_an_interrupt_before_the_first_word_leaves_nothing_heard`, `test_an_interrupt_after_the_last_word_is_not_a_mid_sentence_cut` |
| A stale release cannot clear a live speaker | `test_a_stale_release_cannot_clear_the_current_speaker` |
| A stale tool result is never used | `test_a_lookup_that_outlives_its_turn_is_no_longer_accepted` |
| An abandoned lookup never reaches the transcript | `test_the_answer_to_an_abandoned_question_never_reaches_the_transcript` |
| Handovers never reuse a generation | `test_each_handover_is_a_new_generation` |

And end to end, over a whole scripted interview, in
`tests/test_interruption_journey.py` — because the failure this guards against
is an interaction between three components that are each individually correct:

| Clause | Test |
| --- | --- |
| The transcript holds only what was heard | `test_the_transcript_holds_only_what_the_candidate_heard` |
| The abandoned answer cannot be committed late | `test_the_abandoned_answer_cannot_be_committed_afterwards` |
| It cannot land in the next interviewer's voice | `test_the_abandoned_answer_cannot_land_in_the_next_interviewers_voice` |
| The director reads the truncated answer | `test_the_next_interviewer_is_chosen_from_the_truncated_answer` |
| Nothing is recorded when no word played | `test_an_interviewer_cut_off_before_a_word_played_leaves_no_turn` |
| No turn is ever recorded twice | `test_no_turn_is_ever_recorded_twice` |
| A long interview stays consistent | `test_a_long_interview_with_interruptions_stays_consistent` |

The mechanism under test is a generation fence in `app/panel/floor.py`. Every
handover of the floor increments a counter; any work tagged with an older
generation fails `accepts()` and is discarded rather than spoken. Word-level
timestamps from Rime's websocket streaming mode are what let the cut be placed
exactly, rather than estimated from elapsed time.

## Procedure for the live run

1. Start an interview and answer the opening question with a metric claim, for
   example "we moved retention by four percent". The analytics interviewer
   calls `check_benchmark`, which waits `LOOKUP_DELAY_SECONDS` (3.0 by default,
   raise it to widen the window) before returning.
2. While that lookup is running, or while the interviewer is mid-sentence,
   interrupt and change one part of the request — "sorry, I meant activation".
3. Observe: audio stops, a different interviewer answers the revised request,
   and the transcript ends where the interruption happened.
4. Confirm in the log that the stale lookup was discarded rather than spoken:

   ```
   lookup started for 'retention...' at gen 3
   interrupted analytics at 1240ms; heard '...', dropped '...'
   discarded stale lookup of 'retention...' from gen 3
   ```

5. Confirm the abandoned sentence and the stale benchmark appear nowhere in the
   transcript.

## Results

**Logic proven and wired, audio pending.** The acceptance test passes: 87 tests,
of which 53 cover the interruption claim directly. Four of the five clauses are
proven here without a network. The fifth — that queued Rime audio actually
stops — belongs to LiveKit's playback pipeline and is measured in the live run
below.

The live session drives the same `InterviewSession` object the tests drive,
rather than a parallel implementation, so what is proven above is what runs.
Four seams connect them, in `app/agent.py`:

| Room event | Panel call |
| --- | --- |
| `on_enter` | `panel_opened()` — the hiring manager takes the floor and opens |
| `on_user_turn_completed` | `candidate_interrupted()` if the floor was still held, then `candidate_said()` |
| `transcription_node` | `interviewer_spoke()`, one word at a time, as each is played |
| `speech_created`, once done uninterrupted | `interviewer_finished()` |

The cut point needs no estimation. `transcription_node` sits downstream of audio
synchronisation, so a word reaches it only once it has been played; when the
candidate cuts in, that stream stops. Whatever arrived is what was heard, which
is why `heard_ms() + 1` is the exact cut rather than an approximation of one.

To be filled in before submission, with cached and uncached measurements
labelled separately:

- Time from barge-in to audio stopping: _pending_
- Occurrences of a stale sentence being spoken across N interruptions: _pending_
- Transcript/heard-audio agreement across N interruptions: _pending_

## Limitations

- The floor guard is pure logic. It guarantees the application never *chooses*
  to play stale audio; the stop latency itself belongs to LiveKit's playback
  pipeline and is measured separately in the live run above.
- Word timestamps require two things, not one. `RIME_USE_WEBSOCKET` makes Rime
  *send* per-word offsets; `use_tts_aligned_transcript` makes LiveKit *deliver*
  them to the node that records what played. The second defaults to off, and
  with it off the alignment is discarded silently. The agent now logs how many
  milliseconds of audio each turn timed, and warns on zero.
- Rime reports offsets relative to each synthesis request, and LiveKit issues
  one request per sentence, so the clock restarts at every sentence boundary.
  `WordTimeline` flattens them onto one timeline. Measured on 2026-09-08: a
  13.46s greeting returned 32 timed words whose final offset was 3.42s. Without
  flattening, a cut does not merely land in the wrong place — it keeps the
  opening of every sentence and drops the end of each.
- Tested with three interviewers. The mechanism is not sensitive to panel size,
  but we have not run five.
