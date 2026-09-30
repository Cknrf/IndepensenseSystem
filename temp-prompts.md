(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_sit_and_stay

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sit_and_stay-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sit_and_stay-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  peak rotation 20 °/s
  |a| range 0.93 - 1.11 g, resting ~1.03 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe
  
(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $  python -m indepensense.safety.tests.manual.record_trace adl_lying_down 

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_lying_down-01.csv
  3...
  2...
  1...
  GO

  Wrote 1499 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_lying_down-01.csv
  Achieved 99.9 Hz (target 100), 1 failed reads.
  peak rotation 160 °/s
  |a| range 0.54 - 2.15 g, resting ~1.05 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace fall_sideways 

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_sideways-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_sideways-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  peak rotation 315 °/s
  |a| range 0.38 - 3.65 g, resting ~1.14 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $   python -m indepensense.safety.tests.manual.record_trace fall_backward 

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_backward-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_backward-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  peak rotation 413 °/s
  |a| range 0.31 - 3.73 g, resting ~0.92 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.fall_probe --signals
adl_bending-01.csv has 4 columns, expected 7 (t,ax,ay,az,gx,gy,gz).
It predates gyro recording. Delete it and re-record — a rotation signal cannot be recovered from an accelerometer-only trace.