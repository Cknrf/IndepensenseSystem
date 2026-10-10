# IndepenSense Prototype — User Guide

## Welcome to IndepenSense

IndepenSense is a wearable navigation and safety system designed specifically for blind and visually impaired users. It combines cane-mounted sensors, voice-guided navigation, and haptic (vibration) feedback to provide real-time awareness of your surroundings.

This guide will walk you through all the features and how to use them.

---

## System Overview

### What's in the system?

1. **Wearable Device** (worn in pocket or backpack)
   - Main computer that runs everything
   - Controls all sensors and feedback

2. **Cane-Mounted Sensors**
   - TOP sensor: Detects head-level obstacles (branches, signs, etc.)
   - BOTTOM sensor: Detects foot-level obstacles (curbs, walls, etc.)

3. **Feedback Outputs**
   - **Vibration motors** (3 motors in the device) — provide tactile feedback
   - **Speaker** — provides voice guidance and audio alerts
   - **Buttons** — let you control the system with your hands

4. **Built-in Safety**
   - Fall detection (accelerometer monitors for falls)
   - Emergency alert button
   - Battery monitoring with low-battery alerts

---

## Button Controls

The system has three main buttons. All are on the wearable device:

### 1. **PTT Button (Push-to-Talk)** — Silver/metallic button
**What it does:** Activates voice commands for navigation and questions

**How to use:**
- **Press & hold** to start recording your voice command
- **Release** to send the command
- The system will respond with voice guidance

**Example commands:**
- "Navigate me to the nearest Starbucks"
- "What's around me?"
- "Where am I?"
- "Get my saved places"
- "Change language"

**Feedback while recording:**
- You'll hear a short beep when you press (confirmation)
- The system listens while you hold
- Another beep when you release (command received)

### 2. **Emergency Button** — Red button
**What it does:** Sends an emergency alert to your designated guardians

**How to use:**
- **Press and hold for 2 seconds** to trigger emergency alert
- The system will:
  1. Send SMS to your emergency contacts
  2. Include your GPS location
  3. Call your primary guardian (optional)
  4. Sound an alarm on the device (loud buzzer + all vibration motors)

**When to use:**
- You've fallen and can't get up
- You feel unsafe or threatened
- You're lost and need immediate help
- Any situation where you need urgent assistance

**Note:** You can press again within a few seconds to CANCEL the alert before it fully sends (in case of accidental press)

### 3. **Repeat Button** — Blue button
**What it does:** Controls speech and repeats the last message

**How to use:**
- **Press once** to repeat the last message spoken to you
- **Press while speaking** to stop current speech
- **Press during voice command** to cancel the command

**Example:**
- Navigation system says "Turn left in 50 meters" — press Repeat to hear it again
- Device is speaking and you want it to stop — press Repeat
- Recording a voice command but changed your mind — press Repeat to cancel

---

## Obstacle Detection & Feedback

### How It Works

The system has two ultrasonic sensors on your cane that detect obstacles as you walk:
- Detects obstacles up to **200cm (6.5 feet)** away
- Activates **only while you're walking** (uses accelerometer to detect walking)
- **Standing still = no obstacle alerts** (reduces distractions)

### What You'll Feel

As you walk toward an obstacle, you'll feel **vibration feedback** that gets progressively stronger and faster:

| Distance | Vibration | What it means |
|----------|-----------|---------------|
| 200 cm | Slow, light (8 Hz @ 50%) | Obstacle detected far away |
| 100 cm | Medium speed & strength | Obstacle getting closer |
| 50 cm | Fast, strong (26 Hz @ 90%) | Obstacle is very close |
| 20 cm | Very fast, intense (40 Hz @ 100%) | About to hit obstacle |

### Using Obstacle Feedback

**How to interpret:**
- Feel vibration starting = obstacle detected at ~200cm (typical doorway distance)
- Vibration gets faster & stronger = you're getting closer
- If vibration intensity increases suddenly = suddenly closer object detected
- Vibration stops = obstacle passed or you've moved away

**Best practices:**
- **Use it like echolocation feedback** — responds to your movement speed
- If walking fast toward vibration, **slow down**
- If walking slow, feedback is more gradual (gives you more time)
- **Trust the vibration pattern** — it increases smoothly with distance changes

**What you WON'T hear:**
- No voice announcements for obstacles (only vibration)
- This prevents alert fatigue during normal walking
- Allows you to focus on navigation guidance instead

---

## Voice Navigation

### Starting Navigation

**Say:** "Navigate me to [location name]"

**Examples:**
- "Navigate me to the nearest coffee shop"
- "Navigate me to Grand Central Station"
- "Navigate me to my home"

**What happens:**
1. System confirms the destination
2. You may hear: "Destination confirmed: Starbucks at Main and 5th Street. Ready? Press PTT to confirm"
3. **Press PTT again** to start walking
4. System gives you **turn-by-turn voice guidance**

### Navigation Guidance

**You'll hear:**
- "Turn left in 50 meters" — advance notice of upcoming turn
- "Turn left now" — time to make the turn
- "Continue straight" — keep walking same direction
- "Destination reached" — you've arrived

**During navigation:**
- **Vibration feedback** still works for obstacles
- You can **interrupt** by pressing the Repeat button
- System knows your pace and warns you in time

### Asking Questions

**Say:** "What's around me?" or "Describe my surroundings"

System will tell you:
- Nearby streets and intersections
- Nearby landmarks or businesses
- Relative directions (left/right, ahead)

---

## Vibration Feedback Types

The device uses different vibration patterns for different alerts:

### 1. **Obstacle Feedback** (continuous ramping)
- Smooth, progressively increasing vibration
- Means: "Something ahead, getting closer"
- Activates only while walking

### 2. **Navigation Haptics** (distinct patterns)
- Short, sharp pulses on all 3 motors
- Means: "Turn is coming up" or "confirmation signal"
- Happens during turn instructions

### 3. **Fall Detection** (rapid all-motor pulse)
- All 3 motors vibrating at once, repeatedly
- Means: "Fall detected — system checking if you need help"
- If you don't respond in 10 seconds, emergency alert sends

### 4. **Battery Alert** (slow pulse)
- Single motor, slow steady pulse
- Means: "Battery low (30%) — consider charging soon"
- Gets more frequent as battery drops to critical (20%)

---

## Fall Detection

### How It Works

The system has a built-in accelerometer that:
- Monitors for sudden falls (rapid downward acceleration)
- Waits 2 seconds to confirm you haven't stopped moving (to avoid false alarms)
- If fall confirmed, triggers automatic response

### What Happens After a Fall

1. **You'll hear:** "Fall detected. If you need help, press the emergency button"
2. System gives you 10 seconds to respond
3. **If you press emergency button:** Full emergency alert sends (SMS, calls, etc.)
4. **If you don't respond:** System remains alert and ready to help

### What Falls Won't Trigger

- Sitting down quickly
- Bending over suddenly
- Jumping
- Any motion that doesn't result in a full sustained fall

---

## Battery & Charging

### Battery Status

The device has a rechargeable battery that typically lasts:
- **Full charge:** 6-8 hours of active use
- **Light use:** 12+ hours

### Low Battery Warnings

| Battery Level | What You'll Hear |
|--------------|------------------|
| 30% | Single vibration pulse every 30 seconds |
| 20% | More frequent pulses + voice warning |
| 5% | Urgent warning + rapid pulses |

### Charging

- Connect USB cable to the device
- Charge overnight for full battery
- Can use device while charging

---

## Language Settings

### Changing Language

**Say:** "Change language to [language name]"

**Supported languages:**
- English (default)
- Tagalog
- Spanish (coming soon)

**Example:**
- "Change language to Tagalog"
- Response: "Language changed to Tagalog" (heard in Tagalog)

All subsequent voice guidance will be in that language.

---

## Saved Places

### How to Save a Location

When you arrive somewhere:
**Say:** "Save this place as [name]"

**Examples:**
- "Save this place as home"
- "Save this place as work"
- "Save this place as favorite coffee shop"

System will confirm: "Saved: [name]"

### Using Saved Places

**Say:** "Navigate me to [saved place name]"

**Example:**
- "Navigate me to home"
- "Navigate me to work"

System uses GPS and maps to guide you there.

---

## Emergency & Safety Features

### Emergency Button Contacts

Before using the device, you should have set up:
- **Primary guardian:** Who to call first
- **Secondary contacts:** Additional people to notify
- **Emergency message:** Custom message sent with alert

These are configured during first setup.

### Emergency Alert Process

1. **Press emergency button for 2+ seconds**
2. Loud alarm sounds (buzzer + all vibration motors)
3. SMS sent to all guardian contacts with:
   - Your name
   - Your GPS location
   - Message: "I need help"
4. System may call primary guardian

### Canceling Emergency Alert

- If pressed by accident, **press the button again within 10 seconds** to cancel
- If already sent, guardians will get a follow-up message: "Alert canceled"

---

## Tips for New Users

### Getting Started

1. **First 20 minutes:** Focus on button locations and feedback types
   - Find each button by touch
   - Listen to different feedback sounds
   - Get comfortable with vibration patterns

2. **Next hour:** Try voice commands
   - Say basic navigation commands
   - Practice PTT button (hold = record, release = send)
   - Repeat button for stopping speech

3. **First walk:** Test in familiar area
   - Start with short walk to nearby location
   - Feel how obstacle feedback works
   - Get sense of turning timings

### Best Practices

**For Obstacle Feedback:**
- Don't ignore vibration — it's telling you something
- If it starts suddenly strong, something is very close
- Vibration pattern = exact distance, trust it

**For Navigation:**
- Listen carefully to turn instructions
- Slow down if you miss guidance
- System repeats if you ask (press Repeat button)

**For Voice Commands:**
- Speak naturally, as if talking to someone
- Say complete thoughts ("Navigate me to..." not "...to Starbucks")
- System understands context and incomplete phrases

**For Buttons:**
- Always press PTT button firmly (hold = record, release = send)
- Emergency button requires 2-second press (prevents accidents)
- Repeat button is your "stop" button during speech

---

## Troubleshooting

### System not responding to voice

**Check:**
- Did you hear the recording beep? (means PTT was pressed)
- Did you release the button? (release = send command)
- Are you in a very noisy environment?

**Fix:**
- Try speaking more clearly
- Move to quieter area
- Try asking again

### No vibration feedback

**Check:**
- Are you walking? (feedback only works while walking)
- Is there actually an obstacle ahead?
- Did you check battery level?

**Fix:**
- Walk forward slowly to test
- Battery might be dead — charge device

### Device not finding location

**Check:**
- Is the location a known business or landmark?
- Do you have GPS signal? (need some signal for location)
- Did you say the name clearly?

**Fix:**
- Try a different name for the location
- Try navigating to a nearby major landmark first

### Fall was detected but I didn't fall

**This is normal:**
- False positives happen occasionally
- Just dismiss the alert by doing nothing (it goes away in 10 seconds)
- If it keeps happening, system learns and adapts

---

## Quick Reference

### Buttons at a Glance
- **Silver (PTT):** Hold to record voice commands
- **Red (Emergency):** Press 2+ seconds for emergency alert
- **Blue (Repeat):** Press to repeat speech or stop talking

### Feedback Types at a Glance
- **Ramping vibration:** Obstacle getting closer (walk-only)
- **Sharp pulses:** Navigation cue or confirmation
- **Fast all-motors:** Fall detected or emergency state
- **Slow single motor:** Battery low

### Common Commands
- "Navigate me to [place]"
- "What's around me?"
- "Save this place as [name]"
- "Change language to [language]"
- "Where am I?"

---

## Support & Questions

If something doesn't work as described:
1. **Press the Repeat button** to stop any ongoing speech
2. **Try the action again** (sometimes just retrying works)
3. **Check the quick reference** above
4. **Ask the research team** for help during testing

---

## Safety Reminders

⚠️ **Always remember:**
- This system is an aid, not a replacement for your own awareness
- Stay alert to ambient sounds (traffic, people, etc.)
- Test in familiar areas first
- Keep emergency contacts updated
- Charge device daily for reliable operation
- Fall detection is active automatically (you don't need to enable it)

---

**Thank you for helping us test IndepenSense!**

Your feedback will help us make this system better for all blind and visually impaired users.

Safe travels! 🚀
