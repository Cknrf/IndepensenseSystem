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

I'm not sure regarding the reason, but after some time, the other features in the system doesn't work. For example, the buttons. I'm thinking that since 
it is usually happens after an instace of sending emergency. Maybe there's a lockdown or bug that triggering this? 

I'm not sure, but the features aren't working if using the indepensense service to run the program after the device is turned on. But when manually running the app.py, it is working, or does it have relationship as well that after some time, the system doesn't fully work anymore?

Also, can you check the time being sent in emergency, since upon checking the text message, the time are ahead or advanced, it should reflect the current time

Anyway, there's a problem regarding selecting location as well, in the navigation. It still doesn't choose the nearest one

I'm not sure why, but sometimes I can't ssh to the raspberry pi 5, I think the device/raspi, does fully utlize the full connection or rather the 5g signal. Or it is default to use that? 


I'm not sure why, but upon running app.py, it said 
GPS unavailable ([Errno 2] could not open port /dev/ttyUSB1: [Errno 2] No such file or directory: '/dev/ttyUSB1'). Location intents will be limited.
But I'm sure that the sim7600gh is physically connected, and also the gps that is connected to sim7600gh. What do you think could be the problem?

- In tagalog, let's just call indepensense to be indepensensya, since the readings in tagalog is different in reading indepensense. 

- What would happen in the middle of confirmation, if the emergency button is clicked instead? Would it win, and cancel the confirmation? Can you tell me what would happen

- Is it possible to also add the waiting blip for the start/initialization of the app.py, right after the message up until it is ready? 

- In loading weights, there's a message: 
Warning: You are sending unauthenticated requests to the HF Hub. Please set a HF_TOKEN to enable higher rate limits and faster downloads.
Loading weights: 100%|███████████████████████████████████████████████████████████████████████████████████████████████████| 199/199 [00:00<00:00, 6670.55it/s]
  Warming up qwen3:1.7b (up to 90s if cold)...
Does this mean, that the device/system would need internet first so it can download the models? If so, there would be a problem since we should support fully local (offline) 

- We need to say explicitly the battery status, right after the start of the app.py, so that the user would be aware if they should charge it first or not. 

- How can the system know the location that the user would want, since the STT wouldn't get the exact name of the location. I think that we are using an explicit name that is being passed on the model? just like the Jolibee? or not? 
I'm just concern, regarding the naming of the location that would be said by the user, if it would really get by the system. 

- Regarding the buzzer when an emergency is trigger, I have noticed that it would just play once the rapid stutter, which is not sufficient for it to be noticed by the other people. I mean they would notice it, but they probably would just ignore it
since it just a one time sound. What do you think? I think we should play it three times.

- What are those things that would be in the offline queue? What I mean if not processed because of no internet, but would be processed or done once internet is back? 

- What if the sms in the emergency didn't go through? would be there a retry or none? 

- I have noticed, that there's a timeout right either the sms or the backend. If one of this failed to send, the system would have to wait 30 seconds for it to announce the result message or feedback, which is a long time for the user to know whether it went through or not. 
I think what we should do here, is to have a message right after the first try to send, and just give back immediately the result. If one or both fail, we should just say that we would retry sending it for 30 seconds, then after 30 seconds there should be feedback on it as well. What do you think?

- There's somewhat a conflicting or useless emergency enum in the backend, it includes different types of emergency and one of them is of not having internet connection. And I think it would be useless, since how would the system sent the status or emergency if there's no internet connection in the first place. What do you think? 

- Should I add as well, a capability to send a message to the website? backend? So, we would add an intent here for sending a message to all the guardians in the website? This is for just messaging

- Should I add as well, an non-emergency confirmation. To tell the guardians that the user is fine, it is important as well for them to know the status of the user, especially when there's an emergency that got triggered

- I have noticed as well, that the battery warning doesn't get triggered, particularly what I have tested is the 70% raw readings which is 30 percent in the mathemtical correspond right? 

- Why does it take so much time before the indepensense app.py got even started? I mean it shouldn't be because of the booting of the pi, I think it just takes 25-30 seconds accoridng to the online information. What do you think? 
That's where also my concern emerge, since after turning on the battery which would turn on immediately the pi, there wouldn't be an indicator that the user should wait before the system starts since it is the booting time of the PI. But my problem as well is the time that took before the PI run the app.py. Or is it normal?
But when I run it manually, the app.py, it initalizes fast, than the service. What do you think? 

- I have tested fortunately right now coincidencetialy the battery:
ct 08 08:04:26 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:26 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:30 cknrf python[1446]: [battery] 30% — firing LOW_BATTERY alert
Oct 08 08:04:30 cknrf python[1446]: [telemetry] POST /raspberry/alert succeeded on attempt 1
Oct 08 08:04:36 cknrf python[1446]: [obstacle:bottom] danger at 41 cm (repeat)
Oct 08 08:04:43 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:43 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:04:43 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:44 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:45 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:45 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:46 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:47 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:50 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:50 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:50 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:50 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:51 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:51 cknrf python[1446]: [obstacle:bottom] danger at 54 cm (repeat)
Oct 08 08:04:51 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:04:52 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:52 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:04:54 cknrf python[1446]: [telemetry] POST /raspberry/interval-information succeeded on attempt 1
Oct 08 08:04:59 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:04:59 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:00 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:00 cknrf python[1446]: [sms] timed out after 30.0s: ['--sms=0', '--send']
Oct 08 08:05:00 cknrf python[1446]: [sms] send to +639051675263 attempt 1 failed, retrying in 0.1s: send failed
Oct 08 08:05:01 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:05:01 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:02 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:04 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:05 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:06 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:06 cknrf python[1446]: [obstacle:bottom] danger at 53 cm (repeat)
Oct 08 08:05:07 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:05:07 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:07 cknrf python[1446]: [obstacle:top] warning at 95 cm (entered)
Oct 08 08:05:09 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:09 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:10 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:10 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:10 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:10 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:17 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:18 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:21 cknrf python[1446]: [obstacle:bottom] danger at 54 cm (repeat)
Oct 08 08:05:22 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:22 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:23 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:23 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:23 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:24 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:25 cknrf python[1446]: [telemetry] POST /raspberry/interval-information succeeded on attempt 1
Oct 08 08:05:29 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:30 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:30 cknrf python[1446]: [sms] timed out after 30.0s: ['--sms=1', '--send']
Oct 08 08:05:30 cknrf python[1446]: [sms] send to +639051675263 attempt 2 failed, retrying in 0.5s: send failed
Oct 08 08:05:32 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:33 cknrf python[1446]: [obstacle:top] warning at 54 cm (entered)
Oct 08 08:05:36 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:36 cknrf python[1446]: [obstacle:bottom] danger at 53 cm (repeat)
Oct 08 08:05:37 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:37 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:41 cknrf python[1446]: [obstacle:top] warning at 54 cm (entered)
Oct 08 08:05:41 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:42 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:05:43 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:05:51 cknrf python[1446]: [obstacle:bottom] danger at 42 cm (repeat)
Oct 08 08:05:55 cknrf python[1446]: [telemetry] POST /raspberry/interval-information succeeded on attempt 1
Oct 08 08:06:01 cknrf python[1446]: [sms] timed out after 30.0s: ['--sms=2', '--send']
Oct 08 08:06:01 cknrf python[1446]: [sms] send to +639051675263 attempt 3 failed, retrying in 1.0s: send failed
Oct 08 08:06:07 cknrf python[1446]: [obstacle:bottom] danger at 54 cm (repeat)
Oct 08 08:06:07 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:06:07 cknrf python[1446]: [obstacle:top] clear at 6553 cm
Oct 08 08:06:08 cknrf python[1446]: [obstacle:top] warning at 96 cm (entered)
Oct 08 08:06:09 cknrf python[1446]: [obstacle:top] clear at 6553 cm

Oct 08 08:37:11 cknrf python[1446]: [battery] critical, warning the wearer — gauge 20% (raw 66%), lowest cell 3442 mV
Oct 08 08:37:21 cknrf python[1446]: [obstacle:bottom] danger at 22 cm (repeat)
Oct 08 08:37:24 cknrf python[1446]: [telemetry] POST /raspberry/interval-information succeeded on attempt 1
Oct 08 08:37:24 cknrf python[1446]: [obstacle:top] danger at 27 cm (repeat)

- What if the services failed? I mean those things that we are loading the ram, the ollama, graphhopper, whisper, piper, etc. Would the system would retry loading it? or it is in the background. And what would happen to the system, if they aren't loaded? Since most of the features/functions depend on them, what do you think? 

- I have noticed as well, that there's a battery duration estimate in the message? Let's remove it since it is not accurate enough which would propose a misinformation for the user which is more risky. 

- My coworker also changed the logic for the distance sensing and the feedback, can you check and tell me the mechanism? 

- Whisper and the e5 embedding model try to ping Hugging Face over the cellular network on every boot to check for model updates. Passing local_files_only=True and loading snapshots locally (like MMS already does) closes an offline boot vulnerability and speeds up startup.
I mean, we don't need to update the whisper and e5 model, so let's not check for model updates. 

For context, I would use another sd card, since apparently the one that I'm using is fake. My concern is that so far, configuration files, data, and other 
things that is important aren't documented or saved. But the source code is already in the repo, so it is safe.

Now, you can ssh directly to the raspberry pi 5, but access and read only, don't modify or delete anything, especially using rsync since it would delete 
everything that isn't watched/added in the git. Anyway, I want you to check the raspi, to check all the configurations files, data, and necessary things that
I need to saved or copy to my device. 

Here is the credential, and don't worry about the security or the confidentiality, trust me. 
100.113.232.110 and Mearck123 as the password

But before that, since the pi is currently turned off. We can just as well test again the initialization's speed of the main program which would be run automatically by the indepensense service. 
Even though we have already tested it earlier but this time it is different, since it would be from turned off pi. I want you to just keep ssh to the raspberry pi 5, to connect to it immediately once online/available. 
But I'm not sure how would you observe or monitor it, if it jsut alright if you would just see the logs of the indepensense, then it is fine for you to be late in ssh to the raspberry pi 5. 

- The name of the locations, how would the NLU would know it? 
