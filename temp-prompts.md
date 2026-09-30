*
Things that I want to add: 
- There should be some sort of message that would be played in the initialization part, this is for the good UX. For the blind user to enable to know that the system
is already starting and initializng, for the user to not just awkwardly wait. Since, without this, during the initialization part, it would be all quiet, and it can take up 2-3 minutes which is pretty slow.
So the least we can do about here, is to have some sort of the message, or even just a waiting sound/effects.
- Let's have now the service for the app.py, what I mean by this, is to automatically start the program without manually running it.
- Let's have an intent for shutdown of the PI, but since this is critical, there would be verification/confirmation message first, if the user confirmed or agreed or say yes, then proceed to shutdown. And let's have a goodbye message as well for this to be played

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.sensors.tests.manual.single_mpu6050_test
Reading MPU6050 on I2C bus 1 at 0x68. Ctrl-C to stop.
|a|= 0.99 g | accel(g): x= -0.28 y= +0.92 z= -0.23 | gyro(dps): x=   -0.2 y=   +0.5 z=   +0.9 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= -0.26 y= +0.92 z= -0.24 | gyro(dps): x=   -0.6 y=   -0.9 z=   +0.3 | temp= 33.7°C
|a|= 0.99 g | accel(g): x= -0.27 y= +0.92 z= -0.24 | gyro(dps): x=   -0.1 y=   -1.2 z=   +0.2 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.29 y= +0.92 z= -0.24 | gyro(dps): x=   -0.4 y=   -1.7 z=   +0.5 | temp= 33.4°C
|a|= 0.99 g | accel(g): x= -0.29 y= +0.92 z= -0.24 | gyro(dps): x=   -1.2 y=   -2.1 z=   +2.2 | temp= 33.5°C
|a|= 1.06 g | accel(g): x= -0.37 y= +0.96 z= -0.25 | gyro(dps): x=  +10.5 y=  +13.5 z=   -5.3 | temp= 33.5°C
|a|= 1.00 g | accel(g): x= -0.21 y= +0.95 z= -0.23 | gyro(dps): x=  -21.6 y=  +23.4 z=  -28.9 | temp= 33.6°C
|a|= 0.95 g | accel(g): x= -0.23 y= +0.88 z= -0.26 | gyro(dps): x=   -9.2 y=  +13.9 z=  -25.1 | temp= 33.6°C
|a|= 1.01 g | accel(g): x= -0.29 y= +0.94 z= -0.23 | gyro(dps): x=   -8.0 y=  +14.3 z=  -13.1 | temp= 33.6°C
|a|= 0.95 g | accel(g): x= -0.36 y= +0.87 z= -0.15 | gyro(dps): x=  -13.3 y=   +1.6 z=  -21.7 | temp= 33.5°C
|a|= 0.95 g | accel(g): x= -0.45 y= +0.82 z= -0.16 | gyro(dps): x=   +0.5 y=  -18.9 z=  -34.0 | temp= 33.6°C
|a|= 0.98 g | accel(g): x= -0.51 y= +0.83 z= -0.15 | gyro(dps): x=   +3.3 y=  -29.3 z=  -44.9 | temp= 33.4°C
|a|= 0.93 g | accel(g): x= -0.57 y= +0.71 z= -0.17 | gyro(dps): x=   +7.4 y=  -30.0 z=  -44.8 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.61 y= +0.78 z= -0.11 | gyro(dps): x=   +7.0 y=  -27.9 z=  -29.6 | temp= 33.6°C
|a|= 1.03 g | accel(g): x= -0.73 y= +0.71 z= +0.14 | gyro(dps): x=  +16.4 y=  -20.1 z=  -30.3 | temp= 33.5°C
|a|= 1.01 g | accel(g): x= -0.70 y= +0.62 z= -0.37 | gyro(dps): x=   +5.0 y=  -27.7 z=  -20.1 | temp= 33.6°C
|a|= 1.04 g | accel(g): x= -0.82 y= +0.61 z= -0.18 | gyro(dps): x=   -5.5 y=  -31.2 z=  -17.4 | temp= 33.6°C
|a|= 1.04 g | accel(g): x= -0.77 y= +0.71 z= +0.06 | gyro(dps): x=   -2.8 y=  -17.2 z=  -12.2 | temp= 33.6°C
|a|= 0.85 g | accel(g): x= -0.67 y= +0.51 z= +0.06 | gyro(dps): x=   -1.5 y=  -15.3 z=  -12.0 | temp= 33.5°C
|a|= 1.05 g | accel(g): x= -0.83 y= +0.64 z= -0.03 | gyro(dps): x=   +3.4 y=  -13.2 z=  -10.7 | temp= 33.6°C
|a|= 1.09 g | accel(g): x= -0.84 y= +0.60 z= -0.33 | gyro(dps): x=   -8.7 y=  +51.4 z=  -14.6 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.82 y= +0.55 z= +0.06 | gyro(dps): x=   -1.5 y=  -10.7 z=  -14.8 | temp= 33.6°C
|a|= 0.95 g | accel(g): x= -0.79 y= +0.51 z= +0.10 | gyro(dps): x=   -3.0 y=  -16.4 z=  -12.4 | temp= 33.6°C
|a|= 1.05 g | accel(g): x= -0.91 y= +0.51 z= +0.07 | gyro(dps): x=   +3.6 y=  -21.1 z=  -10.4 | temp= 33.5°C
|a|= 0.88 g | accel(g): x= -0.73 y= +0.47 z= +0.16 | gyro(dps): x=   +6.9 y=  -16.1 z=   -8.8 | temp= 33.6°C
|a|= 0.97 g | accel(g): x= -0.84 y= +0.49 z= +0.06 | gyro(dps): x=   +6.7 y=   -7.3 z=   -5.2 | temp= 33.5°C
|a|= 0.95 g | accel(g): x= -0.83 y= +0.45 z= +0.10 | gyro(dps): x=   +7.6 y=   -5.8 z=   -9.9 | temp= 33.7°C
|a|= 0.96 g | accel(g): x= -0.83 y= +0.47 z= +0.08 | gyro(dps): x=   +1.3 y=   -7.9 z=  -11.0 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.89 y= +0.44 z= +0.12 | gyro(dps): x=   -5.7 y=  -11.7 z=   -5.8 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.89 y= +0.43 z= +0.17 | gyro(dps): x=   -3.0 y=   -4.2 z=   -2.8 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.89 y= +0.43 z= +0.14 | gyro(dps): x=   -1.2 y=  +11.9 z=   +1.8 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.89 y= +0.44 z= +0.11 | gyro(dps): x=   -2.2 y=  +17.9 z=   +4.2 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.88 y= +0.45 z= +0.07 | gyro(dps): x=   +7.2 y=  +14.7 z=  +19.7 | temp= 33.7°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
|a|= 0.00 g | accel(g): x= +0.00 y= +0.00 z= +0.00 | gyro(dps): x=   +0.0 y=   +0.0 z=   +0.0 | temp= 36.5°C
^C
Stopped.
(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.sensors.tests.manual.single_mpu6050_test
Reading MPU6050 on I2C bus 1 at 0x68. Ctrl-C to stop.
|a|= 0.98 g | accel(g): x= -0.26 y= +0.93 z= -0.16 | gyro(dps): x=   -4.5 y=   +2.1 z=   -0.0 | temp= 33.1°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.94 z= -0.16 | gyro(dps): x=   -3.5 y=   -2.6 z=   +0.6 | temp= 33.3°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.95 z= -0.14 | gyro(dps): x=   -3.8 y=   -3.0 z=   +1.9 | temp= 33.2°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.95 z= -0.13 | gyro(dps): x=   -9.2 y=   -1.8 z=   +4.4 | temp= 33.4°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.96 z= -0.09 | gyro(dps): x=   -8.6 y=   -4.3 z=   +9.0 | temp= 33.4°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.95 z= -0.10 | gyro(dps): x=   -5.4 y=   +0.2 z=  +13.4 | temp= 33.4°C
|a|= 1.00 g | accel(g): x= -0.24 y= +0.96 z= -0.10 | gyro(dps): x=   -2.4 y=   -1.9 z=   +8.2 | temp= 33.4°C
|a|= 1.03 g | accel(g): x= -0.20 y= +1.00 z= -0.11 | gyro(dps): x=   -0.1 y=   -5.7 z=  +10.9 | temp= 33.4°C
|a|= 0.96 g | accel(g): x= -0.20 y= +0.93 z= -0.10 | gyro(dps): x=  +10.1 y=   -7.1 z=  +17.3 | temp= 33.5°C
|a|= 0.98 g | accel(g): x= -0.19 y= +0.95 z= -0.13 | gyro(dps): x=   +3.4 y=   -7.1 z=  +19.1 | temp= 33.3°C
|a|= 1.03 g | accel(g): x= -0.16 y= +1.01 z= -0.10 | gyro(dps): x=   -1.8 y=   -1.6 z=  +18.1 | temp= 33.3°C
|a|= 1.01 g | accel(g): x= -0.10 y= +1.00 z= -0.11 | gyro(dps): x=   -9.7 y=   +2.0 z=  +26.6 | temp= 33.4°C
|a|= 0.95 g | accel(g): x= -0.01 y= +0.95 z= +0.01 | gyro(dps): x=   -3.9 y=  +13.3 z=  +16.9 | temp= 33.4°C
|a|= 0.99 g | accel(g): x= +0.01 y= +0.98 z= -0.07 | gyro(dps): x=   +2.6 y=   +3.5 z=  +20.7 | temp= 33.4°C
|a|= 1.02 g | accel(g): x= +0.07 y= +1.01 z= -0.10 | gyro(dps): x=   +2.5 y=   +6.6 z=  +22.0 | temp= 33.5°C
|a|= 1.06 g | accel(g): x= +0.06 y= +1.05 z= -0.06 | gyro(dps): x=   +2.2 y=  +15.3 z=  +13.2 | temp= 33.6°C
|a|= 0.98 g | accel(g): x= +0.10 y= +0.97 z= -0.11 | gyro(dps): x=   -4.6 y=   +6.9 z=  +13.6 | temp= 33.4°C
|a|= 1.01 g | accel(g): x= +0.12 y= +1.00 z= -0.02 | gyro(dps): x=   -5.8 y=   -0.7 z=  +15.4 | temp= 33.4°C
|a|= 1.03 g | accel(g): x= +0.14 y= +1.01 z= -0.10 | gyro(dps): x=   -2.0 y=   +0.2 z=  +15.1 | temp= 33.5°C
|a|= 1.03 g | accel(g): x= +0.23 y= +1.00 z= -0.07 | gyro(dps): x=   +0.3 y=   -1.5 z=   +9.5 | temp= 33.4°C
|a|= 1.01 g | accel(g): x= +0.20 y= +0.98 z= -0.09 | gyro(dps): x=   -0.0 y=   +0.5 z=   +7.2 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= +0.22 y= +0.96 z= -0.10 | gyro(dps): x=   -1.2 y=   -1.6 z=   +6.6 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= +0.23 y= +0.96 z= -0.09 | gyro(dps): x=   -1.0 y=   +1.0 z=   +1.9 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= +0.20 y= +0.97 z= -0.08 | gyro(dps): x=   -1.0 y=   -0.9 z=   -0.2 | temp= 33.5°C
|a|= 0.98 g | accel(g): x= +0.19 y= +0.96 z= -0.08 | gyro(dps): x=   -1.4 y=   -6.7 z=   -4.8 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= +0.20 y= +0.97 z= -0.07 | gyro(dps): x=   +0.2 y=   -2.8 z=   -6.1 | temp= 33.4°C
|a|= 0.97 g | accel(g): x= +0.16 y= +0.95 z= -0.08 | gyro(dps): x=   -3.1 y=   +2.4 z=  -13.4 | temp= 33.5°C
|a|= 1.01 g | accel(g): x= +0.15 y= +0.99 z= -0.09 | gyro(dps): x=   -0.1 y=   +5.8 z=  -22.4 | temp= 33.5°C
|a|= 0.98 g | accel(g): x= +0.11 y= +0.97 z= -0.10 | gyro(dps): x=  -16.3 y=  +14.6 z=  -26.3 | temp= 33.5°C
|a|= 1.01 g | accel(g): x= +0.10 y= +1.00 z= -0.11 | gyro(dps): x=   -2.3 y=  +18.6 z=  -35.3 | temp= 33.5°C
|a|= 0.98 g | accel(g): x= -0.04 y= +0.97 z= +0.05 | gyro(dps): x=  -62.4 y=  -31.9 z=  -36.4 | temp= 33.5°C
|a|= 1.00 g | accel(g): x= -0.07 y= +1.00 z= +0.05 | gyro(dps): x=  -39.2 y=   -6.9 z=  -22.6 | temp= 33.5°C
|a|= 0.96 g | accel(g): x= -0.01 y= +0.95 z= +0.11 | gyro(dps): x=  -14.8 y=   +0.9 z=  -18.2 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.14 y= +0.99 z= +0.13 | gyro(dps): x=  -42.2 y=  -12.9 z=  -21.6 | temp= 33.5°C
|a|= 1.01 g | accel(g): x= -0.20 y= +0.94 z= +0.32 | gyro(dps): x=   +5.6 y=   +6.1 z=  -18.8 | temp= 33.6°C
|a|= 1.08 g | accel(g): x= -0.28 y= +0.95 z= +0.43 | gyro(dps): x=  +28.9 y=  +13.9 z=  -11.8 | temp= 33.5°C
|a|= 1.07 g | accel(g): x= -0.22 y= +1.04 z= +0.14 | gyro(dps): x=  -10.3 y=   -3.7 z=  -15.0 | temp= 33.5°C
|a|= 0.92 g | accel(g): x= -0.27 y= +0.88 z= +0.05 | gyro(dps): x=  +18.0 y=  -16.9 z=  -18.7 | temp= 33.6°C
|a|= 1.03 g | accel(g): x= -0.29 y= +0.99 z= +0.03 | gyro(dps): x=  +13.3 y=  +10.4 z=  -12.4 | temp= 33.5°C
|a|= 1.05 g | accel(g): x= -0.30 y= +0.99 z= +0.21 | gyro(dps): x=   -8.0 y=  +24.5 z=  -27.6 | temp= 33.6°C
|a|= 0.93 g | accel(g): x= -0.32 y= +0.86 z= +0.14 | gyro(dps): x=   -5.4 y=  +13.1 z=  -38.7 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= -0.39 y= +0.90 z= +0.13 | gyro(dps): x=   -2.7 y=   +5.9 z=  -38.3 | temp= 33.6°C
|a|= 1.06 g | accel(g): x= -0.64 y= +0.84 z= +0.04 | gyro(dps): x=  -11.4 y=   +6.9 z=  -37.9 | temp= 33.5°C
|a|= 0.97 g | accel(g): x= -0.58 y= +0.76 z= +0.15 | gyro(dps): x=   -2.3 y=   -1.5 z=  -34.8 | temp= 33.6°C
|a|= 0.93 g | accel(g): x= -0.61 y= +0.69 z= +0.12 | gyro(dps): x=   -0.1 y=   -2.9 z=  -29.0 | temp= 33.6°C
|a|= 0.94 g | accel(g): x= -0.60 y= +0.70 z= +0.16 | gyro(dps): x=   +6.8 y=   +0.9 z=  -27.6 | temp= 33.5°C
|a|= 0.97 g | accel(g): x= -0.66 y= +0.70 z= +0.09 | gyro(dps): x=   -5.6 y=   +6.9 z=  -22.3 | temp= 33.6°C
|a|= 0.94 g | accel(g): x= -0.67 y= +0.64 z= +0.09 | gyro(dps): x=   +0.9 y=   +6.4 z=  -14.5 | temp= 33.6°C
|a|= 0.96 g | accel(g): x= -0.70 y= +0.66 z= +0.09 | gyro(dps): x=   -1.4 y=   +1.2 z=   -3.5 | temp= 33.6°C
|a|= 1.01 g | accel(g): x= -0.74 y= +0.68 z= +0.12 | gyro(dps): x=   -0.9 y=   -2.3 z=   +0.9 | temp= 33.7°C
|a|= 0.99 g | accel(g): x= -0.70 y= +0.68 z= +0.13 | gyro(dps): x=   +0.6 y=   -3.1 z=   +2.1 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.71 y= +0.68 z= +0.14 | gyro(dps): x=   +0.8 y=   -4.3 z=   +1.9 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.69 y= +0.70 z= +0.12 | gyro(dps): x=   -1.0 y=   -1.3 z=   -0.1 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= -0.70 y= +0.69 z= +0.11 | gyro(dps): x=   -0.1 y=   +1.8 z=   -0.6 | temp= 33.5°C
|a|= 0.99 g | accel(g): x= -0.71 y= +0.68 z= +0.13 | gyro(dps): x=   -2.5 y=   +1.5 z=   +1.1 | temp= 33.6°C
|a|= 0.97 g | accel(g): x= -0.68 y= +0.68 z= +0.12 | gyro(dps): x=   +1.2 y=   -2.5 z=   +5.5 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.71 y= +0.69 z= +0.11 | gyro(dps): x=   +6.4 y=   -7.3 z=   +8.6 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.68 y= +0.70 z= +0.14 | gyro(dps): x=  +10.8 y=   -6.7 z=   +9.8 | temp= 33.7°C
|a|= 1.00 g | accel(g): x= -0.68 y= +0.73 z= +0.12 | gyro(dps): x=  +12.2 y=   -8.8 z=  +13.5 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.63 y= +0.77 z= +0.11 | gyro(dps): x=   +8.9 y=   -4.5 z=  +25.9 | temp= 33.5°C
|a|= 1.06 g | accel(g): x= -0.65 y= +0.83 z= +0.15 | gyro(dps): x=   -6.1 y=   -6.3 z=  +42.0 | temp= 33.6°C
|a|= 0.97 g | accel(g): x= -0.58 y= +0.77 z= +0.11 | gyro(dps): x=   +5.8 y=   -7.5 z=  +46.4 | temp= 33.6°C
|a|= 1.09 g | accel(g): x= -0.45 y= +0.98 z= +0.13 | gyro(dps): x=  +24.6 y=   +3.0 z=  +45.5 | temp= 33.7°C
|a|= 0.97 g | accel(g): x= -0.42 y= +0.87 z= +0.07 | gyro(dps): x=   +6.6 y=   +6.0 z=  +35.6 | temp= 33.5°C
|a|= 0.95 g | accel(g): x= -0.38 y= +0.87 z= +0.07 | gyro(dps): x=   -0.4 y=   +5.7 z=  +33.3 | temp= 33.6°C
|a|= 1.03 g | accel(g): x= -0.28 y= +0.99 z= +0.07 | gyro(dps): x=  +15.7 y=  +25.8 z=  +34.2 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.23 y= +0.96 z= +0.07 | gyro(dps): x=  +23.5 y=  +31.9 z=  +26.7 | temp= 33.7°C
|a|= 0.95 g | accel(g): x= -0.19 y= +0.93 z= -0.08 | gyro(dps): x=   +0.7 y=   -4.5 z=  +17.1 | temp= 33.6°C
|a|= 0.96 g | accel(g): x= -0.11 y= +0.95 z= -0.04 | gyro(dps): x=  -14.1 y=   -4.7 z=   +5.3 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.14 y= +0.98 z= +0.02 | gyro(dps): x=  -34.2 y=   +6.4 z=   +2.9 | temp= 33.7°C
|a|= 0.97 g | accel(g): x= -0.09 y= +0.96 z= +0.11 | gyro(dps): x=  -34.4 y=  +11.0 z=   -3.4 | temp= 33.7°C
|a|= 1.06 g | accel(g): x= -0.22 y= +1.03 z= +0.06 | gyro(dps): x=   -5.7 y=   -2.2 z=  -10.5 | temp= 33.7°C
|a|= 1.02 g | accel(g): x= -0.21 y= +0.96 z= +0.26 | gyro(dps): x=  -19.1 y=  -31.0 z=  -13.0 | temp= 33.6°C
|a|= 0.97 g | accel(g): x= -0.18 y= +0.93 z= +0.19 | gyro(dps): x=   -1.0 y=  -18.4 z=  -12.8 | temp= 33.6°C
|a|= 1.03 g | accel(g): x= -0.29 y= +0.98 z= +0.16 | gyro(dps): x=   -1.7 y=  -19.9 z=  -10.9 | temp= 33.7°C
|a|= 1.00 g | accel(g): x= -0.27 y= +0.94 z= +0.22 | gyro(dps): x=  +10.2 y=   -3.6 z=  -10.3 | temp= 33.7°C
|a|= 0.99 g | accel(g): x= -0.26 y= +0.94 z= +0.19 | gyro(dps): x=  +13.9 y=   -9.0 z=   -5.1 | temp= 33.7°C
|a|= 1.01 g | accel(g): x= -0.24 y= +0.97 z= +0.19 | gyro(dps): x=   +2.7 y=  -12.5 z=   +2.0 | temp= 33.7°C
|a|= 1.02 g | accel(g): x= -0.26 y= +0.96 z= +0.22 | gyro(dps): x=   +0.4 y=   -0.5 z=  +15.1 | temp= 33.6°C
|a|= 1.05 g | accel(g): x= -0.23 y= +1.01 z= +0.17 | gyro(dps): x=   +6.5 y=   -0.9 z=  +25.9 | temp= 33.7°C
|a|= 1.02 g | accel(g): x= -0.25 y= +0.97 z= +0.15 | gyro(dps): x=   +5.5 y=   +2.4 z=  +35.1 | temp= 33.6°C
|a|= 0.93 g | accel(g): x= -0.09 y= +0.92 z= +0.09 | gyro(dps): x=   -0.6 y=  +13.5 z=  +27.7 | temp= 33.7°C
|a|= 0.97 g | accel(g): x= -0.03 y= +0.96 z= +0.12 | gyro(dps): x=   +5.0 y=   -2.4 z=  +19.3 | temp= 33.7°C
|a|= 0.95 g | accel(g): x= +0.02 y= +0.95 z= +0.08 | gyro(dps): x=   +0.5 y=   +2.9 z=  +10.6 | temp= 33.7°C
|a|= 0.98 g | accel(g): x= +0.04 y= +0.97 z= +0.14 | gyro(dps): x=   +1.1 y=   -4.3 z=   -1.1 | temp= 33.7°C
|a|= 0.98 g | accel(g): x= +0.01 y= +0.97 z= +0.14 | gyro(dps): x=   +1.2 y=   +8.2 z=  -15.6 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.02 y= +0.99 z= +0.13 | gyro(dps): x=   +7.3 y=   +2.4 z=  -21.4 | temp= 33.7°C
|a|= 0.99 g | accel(g): x= -0.18 y= +0.96 z= +0.12 | gyro(dps): x=  +15.5 y=   -9.2 z=  -22.9 | temp= 33.7°C
|a|= 1.00 g | accel(g): x= -0.16 y= +0.99 z= +0.07 | gyro(dps): x=  +16.4 y=   +0.1 z=  -27.4 | temp= 33.6°C
|a|= 1.00 g | accel(g): x= -0.21 y= +0.98 z= +0.02 | gyro(dps): x=  +16.4 y=   -0.5 z=  -25.6 | temp= 33.7°C
|a|= 1.00 g | accel(g): x= -0.23 y= +0.98 z= +0.01 | gyro(dps): x=  +19.1 y=   -3.8 z=  -18.2 | temp= 33.6°C
|a|= 0.98 g | accel(g): x= -0.24 y= +0.95 z= +0.01 | gyro(dps): x=  +24.7 y=   -3.3 z=  -17.5 | temp= 33.6°C
|a|= 1.07 g | accel(g): x= -0.42 y= +0.98 z= -0.11 | gyro(dps): x=  +22.8 y=   +3.3 z=  -10.1 | temp= 33.7°C
|a|= 0.93 g | accel(g): x= -0.20 y= +0.90 z= -0.11 | gyro(dps): x=  +20.8 y=  +10.0 z=   -1.6 | temp= 33.7°C
|a|= 0.92 g | accel(g): x= -0.28 y= +0.87 z= -0.10 | gyro(dps): x=   +7.7 y=  +10.7 z=   +3.9 | temp= 33.6°C
|a|= 1.03 g | accel(g): x= -0.30 y= +0.97 z= -0.16 | gyro(dps): x=   +3.7 y=   +5.8 z=   +4.3 | temp= 33.6°C
|a|= 0.98 g | accel(g): x= -0.34 y= +0.90 z= -0.19 | gyro(dps): x=   +7.1 y=   -7.4 z=   +3.7 | temp= 33.6°C
|a|= 0.96 g | accel(g): x= -0.24 y= +0.91 z= -0.19 | gyro(dps): x=   +6.0 y=   +3.3 z=   +5.6 | temp= 33.7°C
|a|= 1.01 g | accel(g): x= -0.23 y= +0.97 z= -0.19 | gyro(dps): x=   +1.4 y=   -1.4 z=   +6.7 | temp= 33.7°C
|a|= 0.97 g | accel(g): x= -0.25 y= +0.93 z= -0.15 | gyro(dps): x=   -1.5 y=   -3.5 z=   +6.1 | temp= 33.6°C
|a|= 0.99 g | accel(g): x= -0.23 y= +0.95 z= -0.15 | gyro(dps): x=   -5.5 y=   -0.8 z=   +2.8 | temp= 33.7°C
^C
Stopped.
(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_walking

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_walking-01.csv
  3...
  2...
  1...
  GO

  Wrote 1496 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_walking-01.csv
  Achieved 99.7 Hz (target 100), 4 failed reads.
  |a| range 0.00 - 1.59 g, resting ~1.00 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_walking

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_walking-02.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_walking-02.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 0.70 - 2.70 g, resting ~1.00 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_sitting_hard

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sitting_hard-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_sitting_hard-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 0.96 - 1.05 g, resting ~0.99 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_bending

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_bending-01.csv
  3...
  2...
  1...
  GO
Linux cknrf 6.18.33+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.18.33-1+rpt1 (2026-06-01) aarch64

The programs included with the Debian GNU/Linux system are free software;
the exact distribution terms for each program are described in the
individual files in /usr/share/doc/*/copyright.

Debian GNU/Linux comes with ABSOLUTELY NO WARRANTY, to the extent
permitted by applicable law.
Last login: Wed Sep 30 09:24:41 2026 from 100.104.82.110
cknrf@cknrf:~ $ . go.sh
(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_bending

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_bending-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_bending-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 0.65 - 1.33 g, resting ~1.00 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $ python -m indepensense.safety.tests.manual.record_trace adl_vest_on_table

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_vest_on_table-01.csv
  3...
  2...
  1...
  GO

  Wrote 1500 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/adl_vest_on_table-01.csv
  Achieved 100.0 Hz (target 100), 0 failed reads.
  |a| range 1.00 - 1.03 g, resting ~1.02 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe

(.venv) cknrf@cknrf:~/Desktop/thesis/IndepensenseSystem $  python -m indepensense.safety.tests.manual.record_trace fall_forward

Recording 15s to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_forward-01.csv
  3...
  2...
  1...
  GO

  Wrote 1493 samples to /home/cknrf/Desktop/thesis/IndepensenseSystem/var/traces/fall_forward-01.csv
  Achieved 99.5 Hz (target 100), 7 failed reads.
  |a| range 0.00 - 1.39 g, resting ~0.93 g

  Replay with: python -m indepensense.safety.tests.manual.fall_probe