*
Things that I want to add: 
- There should be some sort of message that would be played in the initialization part, this is for the good UX. For the blind user to enable to know that the system
is already starting and initializng, for the user to not just awkwardly wait. Since, without this, during the initialization part, it would be all quiet, and it can take up 2-3 minutes which is pretty slow.
So the least we can do about here, is to have some sort of the message, or even just a waiting sound/effects.
- Let's have now the service for the app.py, what I mean by this, is to automatically start the program without manually running it.
- Let's have an intent for shutdown of the PI, but since this is critical, there would be verification/confirmation message first, if the user confirmed or agreed or say yes, then proceed to shutdown. And let's have a goodbye message as well for this to be played

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_sitting_hard

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sitting_hard-04.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sitting_hard-04.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 0.07 - 10.64 g, resting ~0.99 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace fall_forward

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_forward-02.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_forward-02.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 0.43 - 6.60 g, resting ~0.94 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

For the land fall, why do I have to stay in the ground for 3seconds? It is not applicable in the real scenario, should we say to our users,
if they ever fall down, they need to stay on the ground for 3 seconds, just for the fall detection to get trigger?