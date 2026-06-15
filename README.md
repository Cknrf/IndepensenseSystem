IndepenSense
Development of an IoT-Based Wearable Navigation and Safety Assistance System with Computer Vision and Guardian Monitoring


Project Overview

IndepenSense is an IoT-based wearable assistive system designed to support individuals with visual or mobility impairments by providing real-time navigation assistance, obstacle detection, and safety monitoring.

The system integrates sensor fusion, computer vision, and remote guardian monitoring to enhance user independence and safety in both indoor and outdoor environments.

The core objective of this thesis is to develop a lightweight, real-time assistive wearable system capable of:
- Detecting environmental obstacles
- Assisting navigation decisions
- Monitoring user safety conditions
- Sending alerts to guardians in real time

System Objectives
The project aims to achieve the following:
- Provide real-time obstacle detection using sensors and computer vision
- Assist navigation through directional feedback (audio/vibration)
- Detect falls or abnormal motion using IMU sensors
- Enable emergency SOS alert triggering
- Allow guardians to monitor user status remotely
- Ensure low-latency edge processing on embedded hardware (Raspberry Pi)

System Architecture
IndepenSense follows a modular edge + cloud hybrid architecture.

1. Wearable Edge Device (Raspberry Pi 5)
Responsible for real-time processing and sensor integration:
- Collects data from all sensors
- Runs computer vision inference
- Executes navigation logic
- Generates feedback outputs (buzzer/vibration/audio)
- 
2. Computer Vision Module
Handles environmental perception:
- Real-time object detection (e.g., obstacles, people, vehicles)
- Scene understanding using lightweight ML models
- Video stream processing via Raspberry Pi camera

3. Sensor Fusion Layer
Combines multiple sensor inputs:
- Ultrasonic distance sensing (DYP-A22)
- Motion tracking (MPU6050 IMU)
- Camera-based detection
- Produces unified environmental awareness output

4. Navigation & Decision Module
Core logic system:
- Determines obstacle proximity risk levels
- Generates directional guidance
- Prioritizes safety-critical responses

5. Guardian Monitoring System
Remote monitoring layer:
- Real-time user status updates
- Emergency alert notifications (SOS, fall detection)
- Activity logs and safety events
- Web/mobile dashboard interface

6. Backend & Communication Layer
Handles system connectivity:
- API server for data exchange
- Real-time communication (WebSockets or MQTT)
- Database storage for logs and events

Core Features

* Navigation Assistance
- Real-time obstacle detection
- Multi-sensor distance estimation
- Audio/vibration-based directional feedback

* Safety Monitoring
- Fall detection using MPU6050 IMU
- Abnormal movement detection
- Emergency SOS trigger system

* Computer Vision Awareness
- Object detection for obstacles
- Real-time camera processing
- Environmental context understanding

* Guardian System
- Live monitoring dashboard
- Emergency notifications
- User activity and safety logs

Hardware Components
- Raspberry Pi 5 (main processing unit)
- DYP-A22 Ultrasonic Sensor (distance measurement)
- MPU6050 IMU (accelerometer + gyroscope)
- Raspberry Pi Camera Module (computer vision input)
- Buzzer (audio feedback)
- Vibration motor (haptic feedback)
- Battery pack (portable power system)
- Optional: GPS module (location tracking)


Software Stack
- Language: Python
- Computer Vision: OpenCV, TensorFlow Lite / PyTorch (lightweight models)
- Database: SQLite / PostgreSQL
- Edge Device OS: Raspberry Pi OS
- Hardware Interface: GPIO, I2C, UART


System Workflow
- Sensors continuously collect environmental data
- Camera captures real-time video stream
- Computer vision module detects obstacles
- Sensor fusion layer combines all inputs
- Navigation module determines risk level and action
- Feedback system triggers vibration/audio output
- Data is sent to backend for guardian monitoring
- Alerts are triggered if emergency conditions are detected