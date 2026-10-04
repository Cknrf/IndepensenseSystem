0. Regarding the emergency SMS, I think the very main reason why it is not being sent is that the user doesn't have currently
the guardian number. But I think it passed correctly the backend (website).
But let's put a message guardrail over it as well, if the system doesn't successfully sent text/sms, it should be loudly/explicitly said to the user, so the user would know. 
The logic would be, if both sms and backend successfully sent, then continue saying "Emergency alert sent to your guardian", but if one fail, just say what failed, and if both, say explicitly that the alert didin't succesfully went through, or something like that. Applied both to tagalog and english.
And we should fix the security block, we should somehow bypass this, since what would send is the system itelf, the raspberry pi 5 itself, so it shouldn't need some sort of verification/confirmation. 

1. I'm seeing the problem, what are the things that we should do to avoid these kind of instances? What is this embedding_probe that you are saying, how can I use it, how can I passed the phrases?
Can we just add many phrases, to cover as much as possible scenarios of different phrases? It wouldn't affect that much the performance right? since the embeddings is very fast? If so, we can just do this. 

2. Let's defer it for now

3. Let's defer it for now

4. Ohh, so the pipeline/flow really take so much seconds, 1-2 seconds for the stt, and 2-5 seconds for the local AI to read the text, considering that it failed on the embedding stage which can take 1 second-ish?, after that it would only now decided that it don't know the answer, which would now trigger "let me think", after that it would be passed on the cloud LLM? 
I really thought, that the "let me think" is after it failed on the embeddings stage, the local llm stage now, but instead it is on the cloud llm stage. Anyway, you are right to save the "Let me think" audio (Pre render)
You are as well right, to give the user an earlier waiting signal, though let's now have the vibration alternative since it would be too confusing for the user, it is used for cue (direction) and feedback as well for when there's an obstacle near, so it is not an option. 
Why, it would tangle up the audio code? for the waiting sound? I mean what could be the possible problem? let's just stop it if there would be another audio that would be played? Please explain it, if there's something that I'm overlooking or don't know

6. You are right regarding the bug, can we also just use embeddings for this one? Or should we go through your suggested fix? of having applying the fuzzy matching to the saved placed system? 
I agree on no warning on failure, if the system can't find the saved place, it should explicly/loudly tell the user or warn the user.
For the timeout, let's just stick to the 4 seconds, I deliberately cancelled that

Let's defer for now the compass calibration. 

7. a. Let's not bruteforce our way here, instead let's just make it more explicit that the LLM should just go to unknown, if it in doubt or don't know what to do
b. You are right regarding this, there should be somehow a debounce or timeout, since the user can accidentally spam the emergency button, let's say a 10 seconds of timeout is already good. 
c. Yes, but I thought we already have a logic for this applied? that if the distance remains, then the buzzer or vibration won't signal. Let's say the distance of the top ultrasonic sensor is 42cm and the bottom is 40cm, and if they aren't changing, then there shouldn't be next signal right. 
But my problem is that, this would only happen if the cane wouldn't move even an inch, but what if the user is just sitting and there's a tendency even if the user is not moving, his hand can move the cane, then it would trigger continously, since we can't expect someone to literally not move their hands or the cane completely. What do you think?
d. Is this a bug? Do you mean that when there's an instance that the microphone recorded an empty or complete silence of audio, the whole code or program would stop running? If so, then it is a big bug, and you are right, this shouln't even the reason for the program or system to stop. And also, we should have an explicit message, for an example "I didn't hear anything, can you tell it to me again?"
e. Yeah, this sounds about right

We should also have a feature of knowing the last message of the user? so that the conversation would be somehow continous? Let's just save one previous message, what do you think? 

Let's do this one at a time, so we can push changes as well to its corresponding category/task. 

Regarding the battery status/percentage, I realized/noticed based on my observation that the real 0 percentage of the battery is on 59% of the reading. Meaning that if the readings is 60% meaning the real remaining percentage is 1%. From this, we could just derive the real right percentage, instead of directly basing from the readings. 

Let's have as well a feature/intent of knowing the signal status, so the user would know it. 


-----------------

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ mmcli -m any --messaging-create-sms="text='test',number='+639051675263'"
  ------------------------
  Messaging | created sms: /org/freedesktop/ModemManager1/SMS/1


Phase 1 — At the desk, ~15 min
  
  1. Emergency SMS actually sends ⚠️ was confirmed broken

  mmcli -m any --messaging-create-sms="text='test',number='+639051675263'"
  Expect: a path like /org/freedesktop/ModemManager1/SMS/1.
  Previously: PolicyKit authorization failed on every single alert.

  2. The five button cues are distinguishable

  python -m indepensense.voice.tests.manual.cue_test
  Expect: you can tell the stop cue from the falling chime. Judge the waiting blip for annoyance over five seconds.
  Needs: headset on.

  3. NLU probes

  python -m indepensense.intents.tests.manual.llm_probe
  python -m indepensense.intents.tests.manual.embedding_probe
  Expect: adversarial group ≥ its old score (now 28 cases, not 25 — read the %, not the count). Embedding: 87.3% capture, 100% precision.
  Tests: the arithmetic prompt fix, the bank expansion.

  ---
  Phase 2 — One voice session, ~20 min

  Start the app, then run these as PTT commands in order. Nine changes get covered here.

  4. Nothing captured ⚠️ was confirmed silent

  Press PTT twice fast. Then record 2 s of silence.
  Expect: "I didn't hear anything. Please say that again." — previously, nothing at all.

  5. The waiting blip

  Ask anything slow — "what is the tallest mountain in the Philippines".
  Expect: soft blips from ~1.5 s in, pausing while "let me think about that" plays, resuming until the answer. Quick commands like "what time is it" should blip
  not at all.

  6. Cancel a command in flight

  Ask something, then press repeat while it's thinking.
  Expect: stop cue, and the answer never arrives. Previously it arrived anyway.

  7. Busy cue

  Press PTT while a command is processing.
  Expect: two low beeps. Previously: silence.

  8. Saved places ⚠️ was confirmed broken 3×

  "Save this place as my home" → "Can you help me go home?"
  Expect: routes immediately, no confirmation prompt. Then "What places have I saved" → reads it back. Then "take me to my clinic" → "…and you don't have a place 
  saved by that name."

  9. Vision + ultrasonic fusion

  Stand ~40 cm from a blank wall. "What's in front of me?"
  Expect: "I can't identify what's in front of you, but something is about 40 centimeters away."

  10. Cellular signal

  "Do I have signal?"
  Expect: strength plus the generation — "strong, at 72 percent, on 4G".

  11. Tagalog numbers ⚠️ was confirmed dropping every digit

  Switch to Tagalog. Ask battery, time, signal.
  Expect: numbers spoken as words — "labinlimang porsyento", not a missing number.

  12. Cloud follow-up

  "What is the tallest mountain in the Philippines?" then "What about the second?"
  Expect: the second is answerable. Previously: "I do not know what you are referring to."

  ---
  Phase 3 — Physical, ~10 min
  
  13. Emergency button ⚠️ was 3 alerts for 3 presses

  Press it three times fast. Then hold and mash for ~25 s.
  Expect: one [sms] attempt from the three presses; continuous buzzing throughout the mash with roughly 3 alerts over 25 s, not 30. Every press buzzes.

  14. Obstacle hysteresis ⚠️ was 136 pulses in 4.5 min

  Stand still ~45 cm from a wall for a minute.
  Expect: one pulse on entry, then a reminder roughly every 15 s — not every 2 s. Wobble your hand ±10 cm: should stay quiet.

  ---
  Phase 4 — Long, passive
  
  15. Battery ⚠️ warning had never fired, ever

  python -m indepensense.power.tests.manual.single_ups_test --csv
  Run it down.
  Expect: the percentage reads lower than the raw gauge, and the 15% warning actually fires (at raw ~66%) with a guardian alert. Neither has ever happened on this
  pack.

  ---
  Deferred
  
  ┌─────────────────────────────┬────────────────────────────────────┐
  │                             │                                    │
  ├─────────────────────────────┼────────────────────────────────────┤
  │ Compass calibration         │ outdoors, and the shake test first │
  ├─────────────────────────────┼────────────────────────────────────┤
  │ Tagalog TTS quality         │ needs a listening study            │
  ├─────────────────────────────┼────────────────────────────────────┤
  │ Object recognition accuracy │ needs the 30-scene test set        │
  └─────────────────────────────┴────────────────────────────────────┘

  ---
  Suggested order: 1 → 2 → 4-12 in one session → 13-14 → 3 whenever → 15 overnight.
  
  Tell me which you want to start with and paste the output. If anything fails I'd rather see the log than a summary.



When sending emergency alert, there should be a message regarding the result status, if it both sent succesffuly since there's no response being said: 

[EMERGENCY BUTTON] Pressed. Firing alert...
[EMERGENCY BUTTON] response: Sending your emergency alert.
[sms] mmcli failed (1): error: couldn't find modem
[sms] modem 8 is gone — re-discovering.
[sms] re-bound to modem 10.
[sms] sent to +639051675263
[alert] delivered on both channels.
[obstacle:top] clear at 155 cm
[obstacle:top] danger at 18 cm (entered)
[obstacle:top] clear at 215 cm
[obstacle:top] danger at 17 cm (entered)
[obstacle:top] clear at 6553 cm
[obstacle:top] danger at 16 cm (entered)
[obstacle:top] danger at 15 cm (still)
[obstacle:top] clear at 6553 cm
[obstacle:top] danger at 14 cm (entered)


