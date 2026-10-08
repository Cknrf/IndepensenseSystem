"""Every spoken response, in every supported language.

Response text used to be inline string literals in `executor.py`. That
made English structural: adding Tagalog would have meant a conditional at
each of ~45 return statements. Here each message has one key and one
entry per language, so a missing translation is visible at a glance and
the executor reads as logic rather than as prose.

Keys are namespaced by the intent that speaks them (`nav.*`, `battery.*`,
`vision.*`). Placeholders use `str.format` fields, and the *same* field
names must appear in every language — the tests enforce both that and
full translation coverage, because a `KeyError` here would surface as the
wearable going silent mid-sentence.

On the Tagalog
--------------

Three deliberate choices a reader should know about.

**Object labels stay in English.** YOLO emits COCO class names
("person", "traffic light"), and Manila speech code-switches freely —
"Nakikita ko ang 2 tao at isang chair" is how people actually talk, while
forcing "ilaw ng trapiko" for traffic light is stilted. `_TL_LABELS`
translates a small set of high-frequency and safety-relevant nouns and
everything else falls through to English on purpose, not by omission.

**Tagalog nouns are not inflected for number.** English needs
"a chair" / "2 chairs"; Tagalog uses the bare noun with a counter
("isang upuan", "dalawang upuan"). So the scene description takes a
different code path per language rather than a shared pluraliser — see
`count_label`.

**The device calls itself "Indepensensya" in Tagalog.** Not a
translation — a respelling, so the MMS Tagalog voice pronounces it the
way a Filipino speaker would. Read with Tagalog phonology, "IndepenSense"
comes out wrong: the final "-se" has no Tagalog reading and the name
arrives mangled, which is a poor introduction from a device whose first
words to its user are its own name. English keeps "IndepenSense".

**Tagalog numbers are spelled out; English ones are not.** A digit is
pronounced by the TTS engine's own text frontend, in the language that
engine thinks it is speaking — which for Tagalog is never Tagalog. See
the `tagalog_number` section below for what that was doing to navigation
cues. Spelling the numeral out also drags in grammar English does not
have: a Tagalog numeral must be *linked* to the noun it counts, and the
linker's form depends on the number, so "{value} metro" is "siyamnapung
metro" but "apat na raang metro".
"""
import math
import re
import sys

# Languages this catalogue covers. Keep in step with `config.PIPER_VOICES`
# plus `config.MMS_VOICES` (TTS is split across two engines — see
# voice/router.py), `config.WHISPER_MODELS` and `config.OCR_LANGUAGES`.
LANGUAGES = ("en", "tl")

FALLBACK_LANGUAGE = "en"


MESSAGES: dict[str, dict[str, str]] = {
    # --- distances ----------------------------------------------------------
    # The unit is its own message rather than part of every sentence that
    # mentions a distance, because which unit applies depends on the value:
    # `speak_distance` picks one of these three. Baking "meters" into the
    # templates is what made the wearable announce a cross-province geocode
    # as "five hundred thirteen thousand six hundred meters".
    #
    # English inflects the noun and Tagalog does not, so the one-kilometre
    # case gets its own key rather than a shared "{value} kilometer(s)"
    # template that would only be correct in one of the two languages.
    "distance.meters": {
        "en": "{value} meters",
        "tl": "{value} metro",
    },
    "distance.kilometers": {
        "en": "{value} kilometers",
        "tl": "{value} kilometro",
    },
    "distance.one_kilometer": {
        "en": "1 kilometer",
        "tl": "isang kilometro",
    },
    # Close range — an arm's length, not a walk. `speak_distance` cannot
    # express these: it floors at 10 metres, so an obstacle 40 cm away
    # would be announced as "10 meters". See `speak_proximity`.
    "distance.centimeters": {
        "en": "{value} centimeters",
        "tl": "{value} sentimetro",
    },

    # --- hardware the user is told to touch ---------------------------------
    # Where each button physically sits, as a word the wearer can act on.
    # Separate from the sentences that use them so that re-fabricating the
    # enclosure is a single edit that cannot leave the two languages
    # disagreeing. See docs/hardware.md for the layout these describe.
    #
    # These were wrong until the layout was checked against the physical
    # device: PTT was recorded as "left" when it is on the right, so every
    # confirmation prompt named the button that *declines*. A wrong position
    # is worse than no position — "press the button" merely leaves the user
    # guessing, while "press the left button" sends them to the one that
    # cancels what they were trying to approve.
    "button.ptt_position": {
        "en": "right",
        "tl": "kanang",
    },
    # The repeat/stop button, borrowed as "no" for the duration of a
    # confirmation. Its everyday job — stop speaking, abandon the command —
    # is what "no" means at a confirmation prompt, so the two readings do
    # not conflict.
    "button.cancel_position": {
        "en": "left",
        "tl": "kaliwang",
    },
    # Named only in `help.capabilities`. No prompt asks the user to press
    # this one, and nothing should: it summons a guardian, so the wearer
    # has to be the only one who decides to reach for it.
    "button.emergency_position": {
        "en": "front",
        "tl": "harapang",
    },

    # --- language switching -------------------------------------------------
    # Spoken in the language being switched TO, so hearing the confirmation
    # verifies the switch worked. A wrong switch is immediately audible.
    "language.switched": {
        "en": "I am now speaking English.",
        "tl": "Tagalog na ang gagamitin ko ngayon.",
    },
    "language.already": {
        "en": "I am already speaking English.",
        "tl": "Tagalog na ang ginagamit ko.",
    },
    "language.unsupported": {
        "en": "I can only speak English and Tagalog.",
        "tl": "Ingles at Tagalog lamang ang kaya kong gamitin.",
    },
    # "fully ready", because this lands after two minutes in which the
    # device has already been talking and its safety features have already
    # been running. A bare "ready" invites the question of what the last
    # two minutes were; "fully" marks the boundary the user is waiting for
    # — the point at which voice commands answer.
    #
    # Tagalog says it by reduplication (`handang-handa`) rather than with
    # an adverb. "Ganap nang handa" would be the literal parallel and is
    # correct, but reads as written Tagalog; this is what someone would
    # actually say out loud, which is the register the rest of the
    # catalogue uses.
    "language.greeting": {
        "en": "IndepenSense is now fully ready. I am speaking English.",
        "tl": "Handang-handa na ang Indepensensya. Tagalog ang ginagamit ko.",
    },
    # Spoken from a pre-rendered file at the very first line of `start()`,
    # before any model is loaded — see `config.STARTUP_AUDIO_DIR`. It has
    # to name the wait explicitly: a blind user cannot see a progress
    # indicator, and two silent minutes reads as a device that never woke.
    # Spoken when the voice stack failed every load attempt and the
    # device is carrying on with safety only.
    #
    # Static, and that is load-bearing: TTS may be the thing that
    # failed, so this has to be replayable from a rendered clip with no
    # engine at all — the same path `system.starting` uses before any
    # model exists.
    #
    # It names what still works rather than only what does not. A user
    # told "voice commands are unavailable" and nothing else cannot know
    # whether the device will still call for help if they fall, which is
    # the one thing they most need to know.
    "system.voice_unavailable": {
        "en": "Voice commands are not available on this start-up. Fall "
              "detection, obstacle warnings and the emergency button are "
              "still working.",
        "tl": "Hindi gumagana ang mga utos sa boses sa pagbukas na ito. "
              "Gumagana pa rin ang pagtukoy ng pagkahulog, ang babala sa "
              "harang, at ang pangemergency na butones.",
    },
    "system.starting": {
        "en": "IndepenSense is starting up. This takes about two minutes. "
              "I will tell you when I am ready.",
        "tl": "Nagsisimula na ang Indepensensya. Aabutin ito ng mga dalawang "
              "minuto. Sasabihin ko po kapag handa na ako.",
    },

    # --- shutdown -----------------------------------------------------------
    # Powering off is the one action the wearable cannot undo for its user:
    # afterwards there is no device left to ask for help with, which is why
    # it is the only intent besides navigation that asks before acting.
    # `{button}` comes from `button.ptt_position`, the same source
    # `nav.confirm_destination` uses. This sentence used to say only "press
    # the button" / "pindutin ang butones" on a device with three of them,
    # which asks someone who cannot see the enclosure to guess — and one of
    # the two wrong guesses sends a guardian an emergency alert.
    "shutdown.confirm": {
        "en": "Do you want to turn off IndepenSense? Press the {button} "
              "button to confirm, or the {cancel} button to cancel.",
        "tl": "Gusto mo bang patayin ang Indepensensya? Pindutin ang {button} "
              "pindutan para sang-ayunan, o ang {cancel} pindutan para "
              "kanselahin.",
    },
    "shutdown.goodbye": {
        "en": "Turning off now. Goodbye, and stay safe.",
        "tl": "Papatayin ko na po. Paalam, at mag-ingat ka.",
    },
    "shutdown.cancelled": {
        "en": "Shutdown cancelled. I am still here.",
        "tl": "Kanselado ang pagpatay. Nandito pa rin po ako.",
    },
    "shutdown.failed": {
        "en": "I could not turn myself off. Please power the device off by hand.",
        "tl": "Hindi ko po mapatay ang sarili ko. Pakipatay na lang po ang device nang manu-mano.",
    },

    # --- navigation ---------------------------------------------------------
    # --- nothing was captured -----------------------------------------------
    # Spoken when a recording is too short to hold speech, or when Whisper
    # returns an empty transcript. Both used to end the voice cycle with a
    # bare `return`: the user heard their stop chime and then nothing at
    # all, which is exactly what a device that has died sounds like. The
    # two cases are not separated because the answer is the same — say it
    # again — and the device cannot honestly tell "you did not speak" from
    # "I could not make that out".
    "voice.nothing_heard": {
        "en": "I didn't hear anything. Please say that again.",
        "tl": "Wala akong narinig. Pakiulit po.",
    },

    "nav.no_destination_heard": {
        "en": "I didn't hear where you want to go. Please try again.",
        "tl": "Hindi ko narinig kung saan ka gustong pumunta. Pakiulit po.",
    },
    "nav.no_gps_for_start": {
        "en": "I can't start navigation without a GPS fix yet.",
        "tl": "Hindi pa ako makakapagsimula ng nabigasyon dahil wala pang GPS signal.",
    },
    "nav.place_not_found": {
        "en": "I couldn't find any place matching '{location}'.",
        "tl": "Wala akong nakitang lugar na tumutugma sa '{location}'.",
    },
    # Said instead of the above when the user has places of their own
    # saved and none of them matched either. Without it a mistyped or
    # misheard label looks identical to a place that does not exist, and
    # the user has no screen to check their list against — they would
    # keep asking for "my clinic" with no idea the wearable never had it.
    "nav.place_not_found_nor_saved": {
        "en": "I couldn't find any place matching '{location}', and you "
              "don't have a place saved by that name.",
        "tl": "Wala akong nakitang lugar na tumutugma sa '{location}', at "
              "wala ka ring naka-save na lugar na ganoon ang pangalan.",
    },
    # --- where a saved place is ---------------------------------------------
    # Four messages rather than one template with optional halves, because
    # the two halves fail independently. The address needs Photon and a
    # network; the distance needs a GPS fix. Saved places are the one
    # destination that works with no network at all — answering "I can't
    # look that up right now" to a place the user themselves pinned would
    # give that up for a reverse-geocode that is nice to have.
    #
    # The label is echoed in every variant. The user asked about a name
    # they chose, and hearing it back is how they catch the wearable
    # answering about the wrong one.
    "place.located": {
        "en": "{label} is near {places}, about {distance} away.",
        "tl": "Ang {label} ay malapit sa {places}, mga {distance} ang layo.",
    },
    "place.located_address_only": {
        "en": "{label} is near {places}.",
        "tl": "Ang {label} ay malapit sa {places}.",
    },
    "place.located_distance_only": {
        "en": "{label} is about {distance} away.",
        "tl": "Ang {label} ay mga {distance} ang layo.",
    },
    # Last resort: the place is saved, but there is neither a network to
    # name it nor a fix to measure from. Coordinates are close to useless
    # spoken aloud — they are here because confirming the place exists and
    # where it was pinned still beats saying nothing, and because
    # `location.near_coordinates` sets the same precedent for the user's
    # own position.
    "place.located_coordinates": {
        "en": "{label} is saved at latitude {lat}, longitude {lon}.",
        "tl": "Ang {label} ay naka-save sa latitude {lat}, longitude {lon}.",
    },
    "nav.started": {
        "en": "Navigating to {destination}. Total distance {distance}. {first_action}",
        "tl": "Papunta na tayo sa {destination}. Ang kabuuang distansya ay {distance}. {first_action}",
    },
    "nav.none_active": {
        "en": "You don't have an active navigation.",
        "tl": "Wala kang aktibong nabigasyon.",
    },
    "nav.cancelled": {
        "en": "Navigation cancelled.",
        "tl": "Kinansela na ang nabigasyon.",
    },
    "nav.nothing_to_repeat": {
        "en": "There is nothing to repeat yet.",
        "tl": "Wala pa akong maiuulit.",
    },
    "nav.start_walking": {
        "en": "Start walking.",
        "tl": "Maglakad na po kayo.",
    },
    "nav.already_at_destination": {
        "en": "You are already at your destination.",
        "tl": "Nasa destinasyon ka na.",
    },
    "nav.walk_to_arrive": {
        "en": "Walk {distance} to arrive at your destination.",
        "tl": "Maglakad ng {distance} para makarating sa destinasyon.",
    },
    "nav.turn_immediately": {
        "en": "{instruction} immediately.",
        "tl": "{instruction} kaagad.",
    },
    "nav.turn_in_distance": {
        "en": "In {distance}, {instruction}.",
        "tl": "Sa {distance}, {instruction}.",
    },

    # Turn verification. Names the turn rather than issuing an order: the
    # wearable cannot reroute, so "turn around" would be advice it has no
    # basis for — the user may be mid-crossing, or may have a reason. What
    # it can honestly do is say what it believes happened.
    "nav.missed_turn": {
        "en": "It looks like you missed the turn. The instruction was: {instruction}.",
        "tl": "Mukhang nalampasan mo ang liko. Ang tagubilin ay: {instruction}.",
    },

    # Turn-to-face. Only two spoken lines in the whole interaction — the
    # turning itself is haptic, because a spoken angle lags the movement it
    # describes and competes with traffic. See navigation/orientation.py.
    "nav.walk_straight_ahead": {
        "en": "Walk straight ahead.",
        "tl": "Dumiretso ka na po.",
    },
    # The give-up line. Says what to do rather than reporting a failure:
    # the user is standing in the street and needs an instruction, not a
    # diagnosis.
    "nav.orientation_gave_up": {
        "en": "Start walking, and I will guide you from there.",
        "tl": "Maglakad na po kayo, at gagabayan ko kayo mula roon.",
    },

    # Progress. Distance only, no time estimate: the remaining seconds
    # would have to come from an assumed walking speed, and GraphHopper's
    # pedestrian profile assumes a brisk 5 km/h that a cane user is
    # unlikely to match. A confident wrong number would have them hurrying.
    "nav.progress": {
        "en": "{destination} is {distance} away.",
        "tl": "{distance} pa ang layo ng {destination}.",
    },

    # Destination confirmation. The geocoder returns the best *guess*, and a
    # user who cannot read a map has no way to notice it picked the branch in
    # the next province — so the wearable reads its choice back and waits for
    # a deliberate press before routing anywhere.
    #
    # `{button}` and `{cancel}` are filled from `button.ptt_position` and
    # `button.cancel_position` rather than written into the sentence, so a
    # rebuilt enclosure is one edit in one place instead of a hunt through
    # every message that names a button.
    #
    # "or wait to cancel" became an explicit button because waiting is a
    # poor way to say no: a field log shows a user standing through the
    # full 13.7 s timeout to decline a destination they had already heard
    # was wrong. Silence still declines — that is the backstop for a user
    # who did not hear the question or is not holding the device — but it
    # is no longer the only way.
    "nav.confirm_destination": {
        "en": "{place}, {distance} away. Press the {button} button to "
              "confirm, or the {cancel} button to cancel.",
        # "kanang pindutan", not "kanan na pindutan" — the ligature is baked
        # into the position values so the template stays a plain
        # substitution rather than growing per-language grammar glue.
        "tl": "{place}, {distance} ang layo. Pindutin ang {button} "
              "pindutan para kumpirmahin, o ang {cancel} pindutan para "
              "kanselahin.",
    },
    # Spoken for both ways of declining — the button and the timeout. One
    # message rather than two because the user's next step is identical:
    # the destination was not accepted, say another one. The key is no
    # longer named for the timeout, since that is now the rarer path.
    "nav.confirm_declined": {
        "en": "Cancelled. Please say where you want to go.",
        "tl": "Kinansela. Pakisabi po kung saan kayo gustong pumunta.",
    },

    # --- saved places -------------------------------------------------------
    # The label is always spoken back. It is the only confirmation the user
    # gets that the wearable heard "my sister's house" and not something
    # else, and a place saved under a misheard label is unreachable —
    # they would have to guess the mishearing to navigate to it.
    "place.saved": {
        "en": "Saved this place as {label}.",
        "tl": "Na-save ko ang lugar na ito bilang {label}.",
    },
    "place.updated": {
        "en": "Updated {label} to this place.",
        "tl": "Na-update ko ang {label} sa lugar na ito.",
    },
    "place.no_label_heard": {
        "en": "I didn't hear what to call this place. Please try again.",
        "tl": "Hindi ko narinig kung ano ang itatawag dito. Pakiulit po.",
    },
    "place.no_gps_to_save": {
        "en": "I can't save this place without a GPS fix yet.",
        "tl": "Hindi ko masi-save ang lugar na ito dahil wala pang GPS signal.",
    },
    "place.deleted": {
        "en": "Forgot the place saved as {label}.",
        "tl": "Kinalimutan ko na ang lugar na naka-save bilang {label}.",
    },
    "place.not_found": {
        "en": "I don't have a place saved as {label}.",
        "tl": "Wala akong lugar na naka-save bilang {label}.",
    },
    "place.unavailable": {
        "en": "I can't save places right now.",
        "tl": "Hindi ako makakapag-save ng lugar sa ngayon.",
    },

    # --- listing saved places -----------------------------------------------
    # Spoken, so length is the whole design problem — a dozen labels read
    # at someone is not a list, it is a wait. `_MAX_SPOKEN_PLACES` caps it
    # and `place.list_truncated` says how many were held back, so the
    # count is never silently wrong. The repeat button stops playback
    # mid-sentence, which is the escape hatch for a long one.
    "place.list_empty": {
        "en": "You haven't saved any places yet. You can say, "
              "save this place as home.",
        "tl": "Wala ka pang naka-save na lugar. Pwede mong sabihin, "
              "i-save mo ito bilang bahay.",
    },
    "place.list": {
        "en": "You have {places} saved.",
        "tl": "Naka-save mo ang {places}.",
    },
    # `get` spells the count out in Tagalog, which brings the linker with
    # it — `tagalog_counter(4)` is "apat na", and a linker has to attach
    # to a noun. So the Tagalog sentence names one ("pang lugar") where
    # English can leave "4 more" bare. The same grammar split that makes
    # `count_label` exist in scene description.
    "place.list_truncated": {
        "en": "You have {places} saved, and {count} more.",
        "tl": "Naka-save mo ang {places}, at {count} pang lugar.",
    },

    # --- volume -------------------------------------------------------------
    # The confirmation is spoken AT the new volume, the same trick the
    # language switch uses: hearing it is the verification. A user who asks
    # for louder and hears the same level knows immediately it did not work.
    "volume.set": {
        "en": "Volume is now {percent} percent.",
        "tl": "{percent} porsyento na ang lakas ng tunog.",
    },
    "volume.at_maximum": {
        "en": "Volume is already at the maximum, {percent} percent.",
        "tl": "Nasa pinakamataas na ang lakas ng tunog, {percent} porsyento.",
    },
    # Says the floor AND why it exists. "I can't" on its own would read as
    # the device being broken; the reason makes it a decision.
    "volume.at_minimum": {
        "en": "I can't go below {percent} percent, or you might not hear me.",
        "tl": "Hindi ko puwedeng ibaba sa {percent} porsyento, baka hindi mo "
              "na ako marinig.",
    },
    "volume.not_understood": {
        "en": "I didn't catch what volume you want. Say louder, quieter, "
              "or a number from {minimum} to {maximum}.",
        "tl": "Hindi ko naintindihan kung anong lakas ang gusto mo. Sabihin "
              "mong palakasin, pahinaan, o isang numero mula {minimum} "
              "hanggang {maximum}.",
    },
    "volume.unavailable": {
        "en": "I can't change the volume right now.",
        "tl": "Hindi ko mababago ang lakas ng tunog sa ngayon.",
    },

    # --- help ---------------------------------------------------------------
    # A user who cannot see a screen also cannot read a manual, so the only
    # place the wearable's capabilities can live is in its own voice.
    #
    # Four things, not twelve. Reading a full catalogue aloud is roughly
    # forty-five seconds nobody sits through and nobody remembers; these are
    # the highest-value asks, and anything else is discoverable by trying.
    #
    # The buttons come first, and they are the reason this message is not
    # purely a list of phrases. Voice commands are discoverable — a user
    # can guess "where am I" and be right. Three unlabelled buttons on an
    # enclosure are not guessable, and one of them calls a guardian, so
    # the cost of learning them by experiment is someone else's phone
    # ringing. They were omitted only because two of the three positions
    # were unrecorded; docs/hardware.md now has all three.
    #
    # This costs length, and the length was already a problem. A field
    # timing shows the previous version taking 16.4 s to speak, with the
    # tester pressing stop partway through. The following sentences were
    # tightened to pay for the new one — "ask what places you have saved"
    # went, being the least safety-relevant line and already implied by
    # the sentence before it — but that only recovered part of it: 273 ->
    # 336 characters in English, 344 -> 422 in Tagalog, so roughly 20 s
    # spoken against 16.4 s.
    #
    # Accepted because of *which* 20 seconds it is. A user who gives up
    # halfway has still heard the buttons, which now come first; under the
    # old order they would have heard the phrase list and missed the one
    # thing they cannot discover by guessing. If this needs to shrink
    # again, split the buttons into their own response rather than
    # trimming them back out of this one.
    "help.capabilities": {
        "en": "I am IndepenSense. I help you walk safely and independently. "
              "The {button} button is for talking to me, the {cancel} button "
              "repeats or stops me, and the {emergency} button calls for "
              "help. Ask me where you are, what is around you, or have me "
              "read text out loud. Tell me where you want to go, or save a "
              "place by name and later ask me to take you there.",
        "tl": "Ako si Indepensensya. Tinutulungan kitang makapaglakad nang "
              "ligtas at malaya. Ang {button} pindutan ay para makipag-usap "
              "sa akin, ang {cancel} pindutan ay para ulitin o ihinto ako, at "
              "ang {emergency} pindutan ay para humingi ng tulong. Itanong mo "
              "kung nasaan ka, kung ano ang nasa paligid mo, o pabasahin ang "
              "nakasulat. Sabihin mo kung saan mo gustong pumunta, o i-save "
              "ang isang lugar at mamaya ay sabihing dalhin mo ako doon.",
    },

    # --- location -----------------------------------------------------------
    "location.no_gps": {
        "en": "I don't have a GPS fix yet.",
        "tl": "Wala pa akong GPS signal.",
    },
    "location.near_places": {
        "en": "You are near {places}.",
        "tl": "Malapit ka sa {places}.",
    },
    "location.near_coordinates": {
        "en": "You are near latitude {lat}, longitude {lon}.",
        "tl": "Ang iyong lokasyon ay latitude {lat}, longitude {lon}.",
    },

    # --- emergency ----------------------------------------------------------
    # Spoken to the *wearer* when the system acts on its own, as opposed to
    # `emergency.sent` which answers a button they deliberately pressed.
    # Automatic fall detection used to notify guardians and say nothing at
    # all to the person lying on the ground, who then had no way to know
    # whether help was coming.
    #
    # Phrased as a statement, not a question: there is no cancel window by
    # design — someone knocked unconscious cannot decline one — so implying
    # they have a choice would be a lie.
    #
    # Present continuous, not past: the alert has been *dispatched*, not
    # confirmed delivered. The outcome follows a few seconds later as one
    # of the `emergency.delivery.*` messages below, and claiming success
    # here would have the wearable contradict itself when the modem fails.
    "fall.detected": {
        "en": "I detected a fall. I am alerting your guardian.",
        "tl": "May natukoy akong pagkahulog. Inaabisuhan ko na ang inyong tagabantay.",
    },

    # --- battery warnings spoken to the wearer ------------------------------
    # The guardian has had an SMS and a dashboard alert since the first
    # threshold; the person carrying the device was the only one not told.
    "battery.low_warning": {
        "en": "Battery is low, {percent} percent remaining. "
              "Please charge the device soon.",
        "tl": "Mababa na ang baterya, {percent} porsyento na lang. "
              "Pakisingil na po ang device.",
    },
    "battery.critical_warning": {
        "en": "Battery critically low at {percent} percent. "
              "The device will shut down soon.",
        "tl": "Kritikal na ang baterya, {percent} porsyento na lang. "
              "Malapit nang mag-shut down ang device.",
    },

    "emergency.local_only": {
        "en": "Emergency alert triggered locally. Guardian dashboard not connected.",
        "tl": "Naitala ang emergency sa device. Hindi konektado ang dashboard ng tagapag-alaga.",
    },
    "emergency.sent": {
        "en": "Emergency alert sent to your guardian.",
        "tl": "Naipadala na ang emergency alert sa iyong tagapag-alaga.",
    },
    "emergency.queued": {
        "en": "Emergency alert could not be sent right now. The system will keep trying in the background.",
        "tl": "Hindi maipadala ngayon ang emergency alert. Patuloy itong susubukan ng sistema.",
    },
    # Spoken the moment the alert is dispatched, before either channel has
    # answered. The wearable used to say `emergency.sent` here on the
    # strength of the HTTP leg alone, which was a lie whenever the modem
    # refused — and the person who just pressed the button had no way to
    # know. One of the `emergency.delivery.*` messages follows it.
    "emergency.sending": {
        "en": "Sending your emergency alert.",
        "tl": "Ipinapadala ko na ang emergency alert mo.",
    },
    # Answers a second press inside the re-arm window. Deliberately does
    # not promise help is coming — the device knows the alert was sent,
    # not that anyone has read it, and the delivery report is the only
    # thing entitled to speak about whether it arrived.
    "emergency.already_sent": {
        "en": "I already sent the alert to your guardian.",
        "tl": "Naipadala ko na ang alerto sa iyong tagapag-alaga.",
    },

    # --- guardian status messages ------------------------------------------------
    "guardian.status_ok": {
        "en": "Letting your guardian know you're fine.",
        "tl": "Ipinapaalam ko sa iyong tagapag-alaga na ikaw ay maayos.",
    },

    # --- emergency delivery outcomes ---------------------------------------
    # One per combination of (backend reached, SMS reached). The wearer is
    # told which channel failed rather than a generic "something went
    # wrong", because the two call for different responses: a failed text
    # with a working dashboard means a guardian watching the website
    # already knows, while both failing means nobody does and the user
    # should get help another way.
    #
    # The success cases (both channels, or the dashboard on a unit with no
    # SMS) reuse `emergency.sent` — the sentence was always correct, it was
    # just being said too early, before anything had been delivered.
    # No modem at all, as distinct from a text that failed to send.
    #
    # `sms_failed` promises the system will keep retrying, and with a
    # modem ModemManager cannot see there is nothing to retry with — the
    # driver reports that case as non-retryable and the background window
    # is skipped entirely. Saying the retry sentence anyway would be the
    # device telling a frightened user that help is still on its way when
    # nothing further will be attempted.
    #
    # So this one promises nothing. It names the cause in words the
    # wearer can act on — the phone connection, not "the modem" — and
    # repeats the instruction from `all_failed`, because calling someone
    # directly is then the only channel left.
    "emergency.delivery.sms_no_modem": {
        "en": "Your guardian was notified on the website, but the phone "
              "connection is unavailable so no text could be sent. Please "
              "also call for help if possible.",
        "tl": "Naabisuhan online sa website ang iyong tagapag-alaga, pero "
              "walang koneksyon sa telepono kaya walang text na naipadala. "
              "Kung posible, tumawag din para sa tulong.",
    },
    "emergency.delivery.sms_failed": {
        "en": "Your guardian was notified on the website, but the text "
              "message did not go through. The system will keep retrying "
              "the text for the next few minutes.",
        "tl": "Naabisuhan online sa website ang iyong tagapag-alaga, pero "
              "hindi maipadala ang text message. Patuloy na susubukang "
              "ipadala ng sistema ang text sa susunod na ilang minuto.",
    },
    "emergency.delivery.no_number": {
        "en": "Your guardian was notified on the website, but no phone "
              "number is saved for a text message. The system will keep "
              "retrying.",
        "tl": "Naabisuhan online sa website ang iyong tagapag-alaga, pero "
              "walang naka-save na numero. Patuloy na susubukan ng sistema.",
    },
    "emergency.delivery.backend_failed": {
        "en": "I sent a text message to your guardian, but could not reach "
              "the website. The system will keep retrying.",
        "tl": "Nakapagpadala ako ng text sa iyong tagapag-alaga, pero hindi "
              "ko maabot ang website. Patuloy na susubukan ng sistema.",
    },
    "emergency.delivery.all_failed": {
        "en": "The system could not reach your guardian right now. It will "
              "keep retrying for the next few minutes. Please also call for "
              "help if possible.",
        "tl": "Hindi agad maabot ng sistema ang iyong tagapag-alaga. Patuloy "
              "itong susubukan sa susunod na ilang minuto. Kung posible, "
              "tumawag din para sa tulong.",
    },

    # --- battery ------------------------------------------------------------
    "battery.unavailable": {
        "en": "Battery monitoring is not available on this device.",
        "tl": "Hindi available ang pagsubaybay sa baterya sa device na ito.",
    },
    "battery.read_failed": {
        "en": "I couldn't read the battery status right now.",
        "tl": "Hindi ko mabasa ngayon ang estado ng baterya.",
    },
    "battery.charging": {
        "en": "Battery is at {percent} percent and charging.",
        "tl": "Ang baterya ay {percent} porsyento at nagcha-charge.",
    },
    "battery.level": {
        "en": "Battery is at {percent} percent.",
        "tl": "Ang baterya ay {percent} porsyento.",
    },

    # --- GPS status ---------------------------------------------------------
    "gps.not_configured": {
        "en": "GPS is not configured on this device.",
        "tl": "Hindi nakaayos ang GPS sa device na ito.",
    },
    "gps.no_fix": {
        "en": "GPS has no fix at the moment.",
        "tl": "Wala pang GPS signal sa ngayon.",
    },
    "gps.locked": {
        "en": "GPS is locked with {satellites} satellites. Signal quality is good.",
        "tl": "Naka-lock ang GPS sa {satellites} satellite. Maayos ang signal.",
    },

    # --- cellular -----------------------------------------------------------
    "cellular.unavailable": {
        "en": "Cellular status is not available on this device.",
        "tl": "Hindi available ang estado ng cellular sa device na ito.",
    },
    "cellular.no_modem": {
        "en": "No cellular modem is detected.",
        "tl": "Walang na-detect na cellular modem.",
    },
    "cellular.check_sim": {
        "en": "Cellular is unavailable. Check that the SIM card is inserted.",
        "tl": "Hindi available ang cellular. Tiyaking nakakabit ang SIM card.",
    },
    "cellular.disabled": {
        "en": "Cellular is disabled.",
        "tl": "Naka-disable ang cellular.",
    },
    "cellular.connecting": {
        "en": "Cellular is still connecting.",
        "tl": "Kumokonekta pa ang cellular.",
    },
    "cellular.no_quality": {
        "en": "Cellular is connected, but signal strength is not reported.",
        "tl": "Konektado ang cellular, ngunit hindi maipakita ang lakas ng signal.",
    },
    # Said when the modem has a network but no data bearer is up.
    # "Registered" and "connected" are different states and used to share
    # an answer, so a user asking "is there internet right now" could be
    # told the signal was strong while nothing could reach the internet.
    # The strength is still worth saying — it is why the connection may
    # be failing — but the headline has to be that data is not working.
    "cellular.registered_no_data": {
        "en": "There is a cellular network at {quality} percent signal, "
              "but no data connection.",
        "tl": "May cellular network na {quality} porsyento ang signal, "
              "pero walang data connection.",
    },
    "cellular.strong": {
        "en": "Cellular signal is strong, at {quality} percent.",
        "tl": "Malakas ang cellular signal, {quality} porsyento.",
    },
    "cellular.medium": {
        "en": "Cellular signal is medium, at {quality} percent.",
        "tl": "Katamtaman ang cellular signal, {quality} porsyento.",
    },
    "cellular.weak": {
        "en": "Cellular signal is weak, at {quality} percent.",
        "tl": "Mahina ang cellular signal, {quality} porsyento.",
    },
    # Same three, naming the network generation. Separate messages rather
    # than a sentence assembled from fragments: where the generation goes
    # is a grammar question, and building it by concatenation is how one
    # language ends up reading as a translation of the other. An
    # unrecognised radio standard falls back to the three above and the
    # generation is simply left unsaid.
    "cellular.strong_on": {
        "en": "Cellular signal is strong, at {quality} percent, on {technology}.",
        "tl": "Malakas ang cellular signal sa {technology}, "
              "{quality} porsyento.",
    },
    "cellular.medium_on": {
        "en": "Cellular signal is medium, at {quality} percent, on {technology}.",
        "tl": "Katamtaman ang cellular signal sa {technology}, "
              "{quality} porsyento.",
    },
    "cellular.weak_on": {
        "en": "Cellular signal is weak, at {quality} percent, on {technology}.",
        "tl": "Mahina ang cellular signal sa {technology}, "
              "{quality} porsyento.",
    },

    # --- time ---------------------------------------------------------------
    "time.current": {
        "en": "It's currently {time}.",
        "tl": "Ganap na {time} ngayon.",
    },

    # --- vision -------------------------------------------------------------
    "vision.camera_unavailable": {
        "en": "The camera is not available on this device.",
        "tl": "Hindi available ang camera sa device na ito.",
    },
    "vision.capture_failed": {
        "en": "I couldn't take a photo right now. Please try again.",
        "tl": "Hindi ako makakuha ng larawan ngayon. Pakiulit po.",
    },
    "vision.no_image": {
        "en": "The camera returned no image.",
        "tl": "Walang larawang naibigay ang camera.",
    },
    "vision.analyze_failed": {
        "en": "I couldn't analyze the image right now. Please try again.",
        "tl": "Hindi ko masuri ang larawan ngayon. Pakiulit po.",
    },
    "vision.nothing_recognized": {
        "en": "I don't see anything I recognize right now.",
        "tl": "Wala akong nakikilalang bagay sa ngayon.",
    },
    # Said instead of the above when the camera recognised nothing but the
    # forward ultrasonic is reporting something close. The wearable used
    # to answer "I don't see anything I recognize" while a sensor on the
    # same device had an obstacle at 42 cm — two subsystems that never
    # spoke to each other, and the less useful one doing the talking.
    #
    # Phrased as "something", never as an identity. The ultrasonic
    # measures whatever is in its cone, which is not necessarily what the
    # camera was looking at, so naming it would be a guess dressed up as
    # a reading.
    "vision.unidentified_obstacle": {
        "en": "I can't identify what's in front of you, but something is "
              "about {distance} away.",
        "tl": "Hindi ko matukoy kung ano ang nasa harap mo, pero may bagay "
              "na mga {distance} ang layo.",
    },
    "vision.i_see": {
        "en": "I see {items}.",
        "tl": "Nakikita ko ang {items}.",
    },
    "vision.read_failed": {
        "en": "I couldn't read the text right now. Please try again.",
        "tl": "Hindi ko mabasa ang teksto ngayon. Pakiulit po.",
    },
    "vision.no_text": {
        "en": "I don't see any readable text.",
        "tl": "Wala akong nakikitang mababasang teksto.",
    },
    "vision.truncated_suffix": {
        "en": "... and more.",
        "tl": "... at iba pa.",
    },

    # --- cloud LLM fallback -------------------------------------------------
    # "offline" and "error" are deliberately different. Being offline is
    # actionable — the user can move somewhere with signal — while a
    # provider failure is not, and conflating them sends the user to look
    # for a signal that was never the problem.
    "cloud.offline": {
        "en": "I need an internet connection to answer that, and I don't have one right now.",
        "tl": "Kailangan ko ng internet para masagot iyan, at wala ako ngayon.",
    },
    "cloud.error": {
        "en": "I couldn't get an answer for that right now. Please try again.",
        "tl": "Hindi ako makakuha ng sagot diyan ngayon. Pakiulit po.",
    },
    "cloud.thinking": {
        "en": "Let me think about that.",
        "tl": "Pag-iisipan ko muna iyan.",
    },

    # --- generic ------------------------------------------------------------
    "generic.unknown_intent": {
        "en": "Sorry, I didn't catch that. Could you try again?",
        "tl": "Paumanhin, hindi ko naintindihan. Pakiulit po.",
    },
    "generic.unknown_status_field": {
        "en": "I don't know how to report on '{field}'.",
        "tl": "Hindi ko alam kung paano iuulat ang '{field}'.",
    },
    "generic.error": {
        "en": "Sorry, something went wrong: {error}",
        "tl": "Paumanhin, may naganap na problema: {error}",
    },
}


# Tagalog for a small set of frequently-seen and safety-relevant COCO
# labels. Everything absent falls through to the English label, which is
# natural in Filipino speech — see the module docstring.
_TL_LABELS: dict[str, str] = {
    "person": "tao",
    "car": "kotse",
    "bus": "bus",
    "truck": "trak",
    "motorcycle": "motorsiklo",
    "bicycle": "bisikleta",
    "dog": "aso",
    "cat": "pusa",
    "chair": "upuan",
    "bench": "bangko",
    "table": "mesa",
    "door": "pinto",
    "stairs": "hagdan",
    "bottle": "bote",
    "cup": "tasa",
    "book": "libro",
    "bag": "bag",
    "tree": "puno",
    "traffic light": "traffic light",
}


# --- Tagalog numerals -------------------------------------------------------
#
# Numbers reach the user as digits inside a template ("{value} metro"), and
# what turns a digit into a sound is the TTS engine's own text frontend --
# which speaks the *voice's* language, not ours. The `tl` slot is filled by
# an Indonesian Piper voice, so espeak-ng expands "90" with Indonesian
# number rules and the wearable says "sembilan puluh metro" in the middle of
# a Tagalog sentence. That is not an accent, it is the wrong language on the
# most safety-relevant word in a navigation cue.
#
# Spelling the number out here makes the output independent of whichever
# engine speaks it, which also removes the problem from the MMS-TTS switch:
# that model is character-level with no number expansion at all.
#
# Native Tagalog numerals were chosen over the Spanish-derived set
# ("nobenta", "dos") that Filipinos often use for measurements. Both are
# idiomatic; native keeps the catalogue in one register rather than mixing
# two, and is the form a Tagalog-speaking examiner will expect to see
# justified.

_TL_ONES = (
    "sero", "isa", "dalawa", "tatlo", "apat",
    "lima", "anim", "pito", "walo", "siyam",
)

# 11-19 are a table rather than "labing" + unit because the final -ng
# assimilates to the following consonant (labin-, labim-, labing-) and the
# spelling is conventional, not derivable. A table is also what a reader
# can check against a dictionary.
_TL_TEENS = (
    "sampu", "labing-isa", "labindalawa", "labintatlo", "labing-apat",
    "labinlima", "labing-anim", "labimpito", "labingwalo", "labinsiyam",
)

# Multiples of ten. The stems are irregular (tatlo -> tatlum, apat ->
# apatna), so these are spelled out too.
_TL_TENS = (
    "", "sampu", "dalawampu", "tatlumpu", "apatnapu",
    "limampu", "animnapu", "pitumpu", "walumpu", "siyamnapu",
)

_TL_VOWELS = "aeiou"


def tagalog_ligature(word: str) -> str:
    """Attach the linker that binds a Tagalog modifier to what it modifies.

    Tagalog does not juxtapose a number and a noun the way English does:
    "dalawa upuan" is ungrammatical, it must be "dalawang upuan". The
    linker has three forms chosen by the modifier's final sound — "-ng"
    after a vowel, "-g" after -n, and a separate word "na" after any other
    consonant.

    This is why the number cannot simply be substituted into "{value}
    metro" as a word: the grammar of the sentence changes with the number
    spoken in it.
    """
    if word.endswith(tuple(_TL_VOWELS)):
        return word + "ng"
    if word.endswith("n"):
        return word + "g"
    return word + " na"


def tagalog_number(n: int) -> str:
    """Spell a non-negative integer in native Tagalog numerals.

    Covers 0-9999, which bounds every number this system speaks: distances
    under a kilometre are spoken in metres (so at most 999), distances above
    it are converted to kilometres first, and object counts are single
    digits. Beyond that the value is returned as digits — the wearable
    keeps talking, and nothing in the current system can reach it.
    """
    if n < 0 or n > 9999:
        return str(n)
    if n < 10:
        return _TL_ONES[n]
    if n < 20:
        return _TL_TEENS[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return _TL_TENS[tens]
        # Every tens word ends in -u, so the enclitic "'t" always applies;
        # there is no consonant case here needing a separate " at ".
        return f"{_TL_TENS[tens]}'t {_TL_ONES[ones]}"
    if n < 1000:
        return _tl_group(n, 100, "daan", "raan", "sandaan")
    return _tl_group(n, 1000, "libo", "libo", "sanlibo")


def _tl_group(n: int, size: int, noun: str, after_na: str, one: str) -> str:
    """Render `n` as "<count> <noun> at <remainder>" for hundreds/thousands.

    `one` is the fused word for a single group ("sandaan", "sanlibo") — a
    lexical irregularity, not "isang daan".

    `after_na` is the form the noun takes when the count's linker is the
    separate word "na": "daan" lenites to "raan" (apat na raan, not apat na
    daan) because Tagalog softens d to r between vowels. "libo" has no such
    alternation, so it passes the same form twice rather than the rule
    being inferred from the spelling.
    """
    count, remainder = divmod(n, size)
    if count == 1:
        head = one
    else:
        linked = tagalog_ligature(tagalog_number(count))
        head = f"{linked} {after_na if linked.endswith(' na') else noun}"
    if remainder == 0:
        return head
    return f"{head} at {tagalog_number(remainder)}"


def tagalog_counter(value: int | float) -> str:
    """Spell a number as the linked modifier of the noun that follows it.

    This is the form that goes into a "{value} <noun>" template: the caller
    writes "{value} metro" and gets "siyamnapung metro".

    Decimals are spoken "<whole> punto <fraction>" — 8.2 km is "walo punto
    dalawang kilometro". The whole part takes no linker because a decimal
    is read as a sequence of numbers rather than as one number modifying
    another; only the last word before the noun is linked. Exactly one
    decimal place can occur: `speak_distance` rounds to 100 m before
    dividing by 1000, so the fraction is always a single digit.
    """
    if isinstance(value, float) and value != int(value):
        whole, fraction = f"{value:.1f}".split(".")
        fraction_word = tagalog_ligature(tagalog_number(int(fraction)))
        return f"{tagalog_number(int(whole))} punto {fraction_word}"
    return tagalog_ligature(tagalog_number(int(value)))


# Vowels that take "an" instead of "a" in English.
_ENGLISH_VOWELS = "aeiou"

# COCO labels whose English plural is irregular.
_IRREGULAR_PLURALS: dict[str, str] = {
    "person": "people",
    "child": "children",
    "mouse": "mice",       # COCO's "mouse" is a computer mouse
    "foot": "feet",
    "tooth": "teeth",
}


def english_plural(label: str, count: int) -> str:
    """English plural + article. 1 -> "a chair", 2 -> "2 chairs"."""
    if count == 1:
        article = "an" if label[:1].lower() in _ENGLISH_VOWELS else "a"
        return f"{article} {label}"
    plural = _IRREGULAR_PLURALS.get(label)
    if plural is None:
        if label.endswith(("s", "x", "z", "ch", "sh")):
            plural = label + "es"
        elif label.endswith("y") and len(label) >= 2 and label[-2] not in _ENGLISH_VOWELS:
            plural = label[:-1] + "ies"
        else:
            plural = label + "s"
    return f"{count} {plural}"


def count_label(label: str, count: int, language: str) -> str:
    """Render "<count> <label>" with that language's number grammar.

    English inflects the noun and leaves the numeral as a digit. Tagalog
    does neither: the noun stays bare and the numeral is spelled out and
    linked to it ("dalawang upuan"). This is why scene description cannot
    share a single pluraliser across languages.
    """
    if language == "tl":
        return f"{tagalog_counter(count)} {_TL_LABELS.get(label, label)}"
    return english_plural(label, count)


def round_speech_distance(m: float) -> int:
    """Round a distance in metres to a value pleasant for speech synthesis.

    "In 87 meters, turn left" sounds robotic. "In 90 meters..." sounds
    natural. Rounds to the nearest 10 m for distances under 100 m,
    nearest 50 m up to 500 m, nearest 100 m beyond. Never returns 0.

    Halves round up (25 -> 30, 650 -> 700). We deliberately avoid the
    builtin `round()` here: it uses banker's rounding (round-half-to-
    even), so `round(6.5)` is 6, not 7 — which would speak 650 m as
    "600 meters". Overstating the remaining distance by a half-step is
    also the safer error for a walking user: they arrive slightly
    early rather than being told to turn after they have passed it.

    Returns a bare number. `speak_distance` is what turns it into words.
    """
    if m < 100:
        return max(10, _round_half_up(m, 10))
    if m < 500:
        return _round_half_up(m, 50)
    return _round_half_up(m, 100)


def _round_half_up(m: float, step: int) -> int:
    """Round `m` to the nearest multiple of `step`, halves going up."""
    return int(math.floor(m / step + 0.5)) * step


# Above this many metres, speak kilometres instead. One kilometre is the
# point where the metre count stops being something a walker can picture:
# "eight hundred meters" is a distance you can feel, "eight thousand two
# hundred meters" is arithmetic.
_KILOMETRE_M = 1000

# And above this, drop the decimal. "8.2 kilometers" is useful precision
# for a walk; "513.6 kilometers" is noise on a number whose only job is to
# tell the user this destination is absurd.
_WHOLE_KILOMETRE_M = 10_000


def speak_distance(metres: float, language: str) -> str:
    """Render a distance as words, choosing the unit to suit the magnitude.

    Under a kilometre it stays in metres, because that is the resolution a
    walking user acts on. At or above, it switches to kilometres — the
    wearable used to announce a cross-province geocode as "513600 meters",
    which Piper reads out in full and nobody can parse.

    The unit word comes from the catalogue above rather than being
    concatenated here, so Tagalog is a translation rather than a special
    case, and the one-kilometre singular stays correct in English.

    English keeps the digits — espeak-ng expands them correctly for the
    English voice. Tagalog cannot, for the reasons set out above
    `tagalog_number`, so the value goes in already spelled out.
    """
    rounded_m = round_speech_distance(metres)
    if rounded_m < _KILOMETRE_M:
        return get("distance.meters", language, value=speak_number(rounded_m, language))

    km = rounded_m / 1000.0
    if rounded_m >= _WHOLE_KILOMETRE_M:
        value: float | int = int(_round_half_up(km, 1))
    else:
        value = round(km, 1)
        if value == int(value):
            # 2.0 -> 2, so it is spoken "2 kilometers" not "2.0 kilometers".
            value = int(value)

    if value == 1:
        return get("distance.one_kilometer", language)
    return get("distance.kilometers", language, value=speak_number(value, language))


def speak_proximity(centimetres: float, language: str) -> str:
    """Render a close-range distance — reaching distance, not walking.

    Separate from `speak_distance` because that one is built for
    navigation and floors at 10 metres: an obstacle 40 cm away would come
    out as "10 meters", which is worse than saying nothing.

    Rounded to the nearest 10 cm. The DYP-A22 is specified to ±1 cm under
    ideal conditions and does considerably worse against a soft or angled
    surface, so a figure like "forty-three centimetres" would claim a
    precision the sensor does not have and the user cannot act on anyway.

    Floors at 10 cm rather than reporting smaller values honestly: below
    that the obstacle is already touching, the exact number has stopped
    mattering, and the DYP-A22's own minimum range is 2 cm.
    """
    if centimetres >= 100:
        return speak_distance(centimetres / 100.0, language)
    rounded = max(10, _round_half_up(centimetres, 10))
    return get("distance.centimeters", language, value=speak_number(rounded, language))


def speak_number(value: int | float, language: str) -> str:
    """The form a number takes inside a template, for the given language.

    Public because `get()` does not convert numeric fields — callers hand
    it finished strings — so anything putting a number into a Tagalog
    message has to come through here. Digits are effectively untrained in
    the MMS-TTS Tagalog voice (see `voice/mms.py`), which makes this the
    difference between a spoken number and a dropped one.
    """
    if language == "tl":
        return tagalog_counter(value)
    return str(value)


# Hours 1-12 as Tagalog ordinals. A table, for the same reason `_TL_TEENS`
# is one: the series is not derivable. "ikalawa" and "ikatlo" drop syllables
# the cardinals keep (dalawa, tatlo), so "ika-" + `tagalog_number` would
# produce "ikadalawa" and "ikatatlo" — forms a Tagalog speaker would hear as
# wrong. Twelve entries is also the whole domain, so there is no general
# rule left unimplemented.
_TL_HOUR_ORDINALS = (
    "ikalabindalawa",                                    # index 0 == 12
    "ikaisa", "ikalawa", "ikatlo", "ikaapat", "ikalima",
    "ikaanim", "ikapito", "ikawalo", "ikasiyam", "ikasampu",
    "ikalabing-isa",
)


def _tagalog_day_part(hour24: int) -> str:
    """The part-of-day word that follows the hour.

    Tagalog divides the day into five named stretches, not two halves, so
    there is no word for "AM" to translate. 2 a.m. is `madaling araw`, not
    `umaga` — calling it morning would be understood but is wrong, and noon
    has its own word rather than being the twelfth hour of anything.
    """
    if hour24 < 5:
        return "madaling araw"
    if hour24 < 12:
        return "umaga"
    if hour24 < 13:
        return "tanghali"
    if hour24 < 18:
        return "hapon"
    return "gabi"


def speak_clock(hour24: int, minute: int, language: str) -> str:
    """A wall-clock time as the words to speak it in `language`.

    Why a helper and not a `{hour}:{minute}` template: the sentence
    *structure* differs, not just the words. English joins the two numbers
    with a colon and appends AM/PM; Tagalog links them with "at", counts
    the minutes as a noun phrase ("apat na minuto") and names the part of
    day. An exact hour drops the minute clause entirely in Tagalog, which
    a format string cannot express.

    This exists because `_handle_system_time` used to pass a finished
    `"1:04 PM"` string. `get()` routes numbers through `speak_number` but
    deliberately leaves strings alone, so the digits reached the MMS
    Tagalog voice untouched — and digits are effectively untrained in that
    voice, so the time arrived garbled or missing while reading perfectly
    in English. The fix is to stop pre-formatting, not to special-case
    strings in `get()`.
    """
    if language != "tl":
        # 12-hour with no leading zero: "1:04 PM", "11:30 AM".
        period = "AM" if hour24 < 12 else "PM"
        hour12 = hour24 % 12 or 12
        return f"{hour12}:{minute:02d} {period}"

    hour_word = _TL_HOUR_ORDINALS[hour24 % 12]
    day_part = _tagalog_day_part(hour24)
    if minute == 0:
        return f"{hour_word} ng {day_part}"
    return f"{hour_word} at {tagalog_counter(minute)} minuto ng {day_part}"


def join_items(items: list[str], language: str) -> str:
    """Comma-and join for spoken lists, with the language's conjunction."""
    conjunction = "at" if language == "tl" else "and"
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} " + items[-1]


_PLACEHOLDER = re.compile(r"\{\w+\}")


def static_keys() -> list[str]:
    """Keys whose text is fixed in every language.

    "Fixed" means no `{placeholder}`, so `get()` returns the same string
    on every call and the audio for it can be rendered once and replayed
    forever — see `voice/clips.py` and the `render_messages` tool.

    A key is static only if *no* language templates it. That is the
    conservative direction: a message templated in Tagalog and fixed in
    English is excluded, which costs one synthesis and cannot cause the
    wearable to replay a clip with last week's number in it.

    Derived from `MESSAGES` rather than listed by hand, because a
    hand-kept list is a list that silently stops matching. The three
    messages this replaced were a hardcoded dict of nicknames, and
    `language.greeting` — static, spoken on every boot — had never been
    added to it.
    """
    return sorted(
        key for key, entry in MESSAGES.items()
        if not any(_PLACEHOLDER.search(text) for text in entry.values())
    )


def get(key: str, language: str, **fields) -> str:
    """Look up a message and fill in its placeholders.

    Falls back to `FALLBACK_LANGUAGE` for a missing translation and to the
    key itself for a missing message: speaking something odd beats
    raising inside the voice pipeline, where the exception would surface
    to the user as silence.
    """
    entry = MESSAGES.get(key)
    if entry is None:
        print(f"[messages] unknown key {key!r}", file=sys.stderr)
        return key

    template = entry.get(language)
    if template is None:
        print(
            f"[messages] {key!r} has no {language!r} translation; using "
            f"{FALLBACK_LANGUAGE!r}",
            file=sys.stderr,
        )
        template = entry[FALLBACK_LANGUAGE]

    # Spell numbers out, here rather than at each call site.
    #
    # The MMS Tagalog voice has digits in its vocabulary but they are
    # effectively untrained — the MMS-lab corpus writes numbers as words
    # — so "15 porsyento" reaches the speaker as something between
    # garbled and missing. `speak_distance` already knew this and routed
    # through `speak_number`; nothing else did, which left every battery
    # percentage, volume level, satellite count and signal strength
    # silently dropping its number in Tagalog.
    #
    # Centralised because the failure is invisible from the code. A
    # caller passing `percent=15` looks correct, reads correctly in
    # English, and is only wrong in a language the author may not speak.
    # Expecting twelve call sites to remember forever is how it got here.
    #
    # Numbers only. Strings pass through untouched, so a pre-formatted
    # value — a clock time, a coordinate — stays exactly as the caller
    # intended rather than being re-interpreted.
    spoken = {
        name: speak_number(value, language) if isinstance(value, (int, float))
        and not isinstance(value, bool) else value
        for name, value in fields.items()
    }

    try:
        return template.format(**spoken)
    except (KeyError, IndexError) as exc:
        print(f"[messages] {key!r} missing placeholder {exc}", file=sys.stderr)
        return template
