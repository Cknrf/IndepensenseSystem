# Semantic fast-path example bank

Labelled utterances for the embedding matcher in `intents/embeddings.py`.
Each one is encoded once at startup; an incoming transcript is matched
against the whole bank by cosine similarity. The nearest neighbour's
section heading decides the answer.

**This file is data, not prose.** Parsing rules:

- `## <label>` opens a section. Everything until the next `##` is one
  utterance per line.
- Blank lines and lines starting with `#` (outside a heading) are ignored.
- A label of the form `intent.name:value` carries a closed-enum slot —
  `device.status:battery` means `Intent.DEVICE_STATUS` with
  `{"status_field": "battery"}`. See `_ENUM_SLOT_KEYS` in `embeddings.py`.
- A label starting with `__escalate__` means "this must go to the LLM".
  The text after it is a human-readable bucket name, ignored by the code
  but reported by `embedding_probe` so you can see which kind of
  escalation is winning.

Everything above the first `##` is preamble and is never parsed, so the
notes below are safe to keep here. Do not introduce an `##` heading that
is not a class label — the parser rejects labels it does not recognise
rather than silently treating prose as training data.

**Why only these intents.** The matcher can only answer intents whose
parameters are fully determined by the label. A sentence embedding is one
vector for the whole utterance — it can say *which* intent, never *which
span of text* is the destination. So `navigation.start` (open `location`),
`place.save` / `place.delete` (open `label`), `system.volume` with a
numeric level, and `system.language` naming an unsupported language are
all escalations by construction, not by low confidence. They appear below
only as negative examples.

**Keep this disjoint from the probe.** The cases in
`tests/manual/llm_probe.py` are the held-out test set. Do not copy
utterances from there into this file — the measured accuracy would be
reporting memorisation instead of generalisation, which is not a number
worth putting in a thesis. Write fresh phrasings here.

**Both languages, every class.** Tagalog is the priority language. A class
with English examples only will match English transcripts and silently
escalate every Tagalog one, which looks like "the fast path is safe" while
actually meaning "the fast path does not serve half the users".

**Adding examples can make things worse. Measure.** The gate is score
*and* margin, and margin is the gap to the nearest example of a different
class — so a new row raises its own class and lowers its neighbours'
margins at the same time. Adding "Can you tell me what you can do" to
`system.help` cost "Can you jump me the time?" its margin and turned a
working `system.time` match into an escalation. Nothing in the diff looked
wrong; only the probe caught it.

Two rules follow:

- **Carrier phrases must bring their class's own vocabulary.** "Can you
  tell me..." is shared noise across every class. An example that is
  mostly carrier lands in the middle of the space and steals margin from
  everything near it. "Can you tell me what this device can do" is safe;
  "Can you tell me what you can do" was not.
- **Re-run the probe after every edit**, and read *precision* first:

      python -m indepensense.intents.tests.manual.embedding_probe
      python -m indepensense.intents.tests.manual.embedding_probe --try-file field.txt

  Capture is a convenience number — a miss costs latency and the LLM
  still answers correctly. Precision is the safety number: a drop there
  means the wearable takes a wrong action. Never accept an edit that
  lowers it.

## navigation.stop

Stop navigating
Stop guiding me
Cancel the route
End the navigation
Never mind the directions
I don't want to go there anymore
Quit the trip
Stop

Itigil mo na ang pagbibigay ng direksyon
Kanselahin mo ang ruta
Huwag mo na akong gabayan
Tama na ang navigation
Ayoko na pumunta doon
Tigil na sa pagtuturo ng daan
Ihinto mo na

## navigation.repeat

Repeat that
Say it again
Come again
What did you say
Can you repeat that please
One more time
Repeat the last direction
I missed that

Pakiulit nga
Ulitin mo ulit
Ano ulit yung sinabi mo
Pakiulit mo yung direksyon
Hindi ko narinig, pakiulit
Isa pang ulit
Ulitin mo yung huli

## navigation.location

Where am I right now
What street am I on
Tell me where I am standing
What is my position
Which place is this
What address is this
Where exactly am I

Nasaan ba ako ngayon
Saan ako naroroon
Anong kalye ito
Saang lugar ako nakatayo
Sabihin mo kung nasaan ako
Anong address ito
Saan ba ako

# Carrier phrases — see the note under `vision.describe`. Deliberately
# leaning on place / street / address rather than "around me": this class
# and `vision.describe` sit close enough already that "what is around me"
# split them by 0.001 in the field log, and giving both the same spatial
# vocabulary would make that worse rather than better.
Can you tell me what street I am on
Could you tell me my current location
I want to know what place this is
What is my location right now

Pwede mo bang sabihin kung anong lugar ito
Gusto kong malaman kung nasaang kalye ako
Ano ang kasalukuyan kong lokasyon

## navigation.progress

How far is left
Are we almost there
How long until I arrive
What is the remaining distance
How much of the trip is left
Am I close to the destination
How many minutes more

Malayo pa ba
Malapit na ba tayo
Gaano katagal pa bago makarating
Ilang minuto na lang
Gaano pa kalayo ang natitira
Malapit na ba ako sa pupuntahan
Ilan pang metro

## emergency.trigger

# The bare tokens "help" and "tulong" are deliberately ABSENT. They are
# the two most important utterances on the device, and they are also
# held-out test cases in `llm_probe`. Anchoring them here would make the
# probe report memorisation on exactly the case whose reliability matters
# most.
#
# Measured: both generalise correctly from the phrasings below, so they
# stay out and the probe's emergency result stays honest. If a future
# bank edit breaks that, `embedding_probe` fails on them before anything
# reaches the device — and the fix at that point is an explicit anchor
# here plus a note in the thesis that those two cases are no longer held
# out. Safety wins that trade; it just has not had to be made yet.
Help me please
This is an emergency
Somebody help me
Call for help
I am in trouble
Emergency
I need urgent help
Please send help

Saklolo
Tulungan niyo ako
May emergency
Tulong naman po
Tumawag kayo ng tulong
Tulungan mo ako ngayon
Kailangan ko ng tulong agad

# Field testing surfaced a gap: every example above is the user in
# distress, and none of them is the user *instructing the device*. "Can
# you send an emergency?" went to the LLM because the bank had no
# request-shaped phrasing of the most important intent on the wearable.
# These add the instruction form, and name the guardian explicitly —
# "alert my guardian" has no distress words in it at all, so nothing
# above would have been near it.
Send an emergency alert now
Can you send an emergency alert
Alert my guardian
Contact my guardian right now
Tell my guardian I need help
Notify my guardian immediately

Ipadala mo na ang emergency alert
Pwede mo bang ipadala ang emergency
Abisuhan mo ang tagabantay ko
Sabihan mo ang tagapag-alaga ko
Ipaalam mo sa tagabantay ko na kailangan ko ng tulong

## guardian.status_ok

I'm fine
I'm okay
Tell my guardian I'm safe
Let my guardian know I'm fine
Everything is okay
I'm alright
I'm doing well
Tell them I'm safe now
I'm good

Ayos lang ako
Maayos ako
Sabihin mo sa tagapag-alaga ko na ako ay maayos
Ipaalam mo sa guardian ko na ligtas ako
Lahat ay okay
Okay na ako
Buti na ako
Sabihin mo na kami ay safe
Okay lang

## system.time

What time is it now
Do you know the time
Tell me the time
What is the time
Could you tell me the time please
May I know the time

Anong oras na ba ngayon
Alam mo ba kung anong oras na
Sabihin mo nga ang oras
Pakisabi ang oras
Anong oras na po

# Carrier phrases — see the note under `vision.describe`.
Can you tell me the time right now
I want to know the time
Do you have the time

Pwede mo bang sabihin ang oras ngayon
Gusto kong malaman kung anong oras na

## system.help

What are your features
How does this device work
What commands can I use
Tell me what you are able to do
How do I use this device
What are you for
What should I say to you
# "help" appears in the most natural phrasings of this question, which
# puts them next to `emergency.trigger` in embedding space. The cost of
# that confusion is asymmetric — answering a cry for help by listing
# features, or alerting a guardian because someone asked what the device
# does — so the overlap is broken here with explicit examples rather than
# left to the margin.
How can you help me
What kind of help can you give
In what ways can you assist me
What are you able to help with

Anong mga kaya mong gawin
Paano ba gamitin itong device
Anong mga utos ang pwede kong sabihin
Ituro mo kung paano ito gamitin
Para saan ka ba
Anong pwede kong itanong sayo
Paano mo ako matutulungan
Anong klaseng tulong ang kaya mong ibigay

# Carrier phrases — see the note under `vision.describe`.
#
# "Can you tell me what you can do" was here and had to go: almost all of
# it is carrier, with "what you can do" carrying no content a short query
# can latch onto. It landed 0.884 from "Can you jump me the time?" and
# cost that transcript its margin — a system.time case the fast path used
# to answer. A carrier example has to bring its class's own vocabulary
# with it ("device", "features", "commands") or it just sits in the
# middle of the space stealing margin from everything.
Can you tell me what this device can do
Could you list the features of this device
I want to know what this device can do
What commands does this device understand

Pwede mo bang sabihin ang mga kaya mong gawin
Gusto kong malaman kung ano ang magagawa mo

# Questions ABOUT the emergency feature are help, not an emergency. They
# share every content word with the emergency class, so they need anchors.
How does the emergency alert work
How do I use the emergency button
Paano gamitin ang emergency button

## system.shutdown

Power off
Turn the device off
Shut the system down
Switch off IndepenSense
Power down now
Turn yourself off

Patayin mo na ito
I-off mo na ang device
Isara mo na ang sistema
Patayin mo na ang IndepenSense
I-shutdown mo na
Patayin mo na ang makina

## vision.describe

Describe what is in front of me
Tell me what you see
What is around here
Describe the scene
What is in front of me
Look around and tell me
What things are near me

Ilarawan mo ang paligid
Ano ang nasa harap ko
Sabihin mo kung ano ang nakikita mo
Anong mga bagay ang nasa paligid ko
Tignan mo nga ang paligid
Ilarawan mo nga ang nasa harapan

# Carrier phrases. Real users do not speak in bare imperatives — the
# field log is full of "Can you tell me...", "Could you...", "I want you
# to...", and the bank had almost none of it. See the note above the
# escalate sections for why these are added to several classes at once
# rather than only to the one that missed.
#
# Each keeps its class's distinctive content words (see / objects /
# around) rather than leaning on the carrier, which is shared noise: it
# is the content that has to carry the margin.
Can you tell me what you see
Could you describe what is near me
Tell me what objects are around me
What do you see right now
I want you to describe my surroundings

Pwede mo bang sabihin kung ano ang nakikita mo
Maaari mo bang ilarawan ang nasa paligid ko
Gusto kong malaman kung ano ang nasa harap ko
Anong mga bagay ang nakikita mo ngayon

## vision.read

Read the text
What does this label say
Read this sign out loud
Read the receipt for me
What is written here
Read what is on the paper
Read the writing

Basahin mo ang nakasulat
Anong nakasulat dito
Pakibasa nga ito
Basahin mo yung karatula
Anong sabi ng papel na ito
Pakibasa ang resibo
Basahin mo nga ang nasa harap

# "help me" + reading is a reading request, not a cry for help. Without
# these, "help me read ..." sat closest to "Help me please".
Help me read the label
Help me read this letter
Tulungan mo akong basahin ito

## place.list

# Answerable by the fast path, unlike its `place.save` / `place.delete`
# siblings: it names no place, so there is no span to extract. The
# distinction the examples have to carry is between asking about the
# *list* and asking about *one entry on it* — "what have I saved" against
# "is my home saved". Only the first is this intent; the second has no
# intent at all and sits under `__escalate__:place` below.

What places have I saved
Which places have I saved
List my saved places
What are my saved places
Read back my saved places
Tell me the places I saved
What locations do I have saved
Name the places you remember for me
What have I saved so far

Anong mga lugar ang naka-save ko
Anong mga lugar ang na-save ko
Ilista mo ang mga naka-save kong lugar
Basahin mo ang mga naka-save na lugar
Sabihin mo ang mga lugar na tinandaan mo
Anong mga lugar ang natatandaan mo
Ano-ano ang mga naka-save kong lugar

## device.status:battery

How much battery is left
What is the battery level
Is the battery low
Check the battery for me
Battery status
How much charge do you have
Do you need charging

Ilan pa ang natitirang baterya
Mababa na ba ang baterya
Pakicheck ang baterya
Anong level ng baterya
Kailangan mo na bang i-charge
Ilan na lang ang baterya mo

## device.status:gps

Do you have a GPS signal
Is the GPS working
Check the GPS
Is the GPS locked on
GPS status
Can you find satellites

May GPS signal ka ba
Gumagana ba ang GPS
Pakicheck ang GPS
Nakakonekta ba ang GPS
Nakakakuha ka ba ng satellite

## device.status:signal

Do I have network signal
Is there internet right now
How is the connection
Check the signal
Are you online
Is the mobile data working

May signal ba tayo
May internet ba ngayon
Kumusta ang koneksyon
Pakicheck ang signal
Online ka ba
Gumagana ba ang data

## system.volume:up

Make it louder
Turn it up
Increase the volume
I cannot hear you
Speak up
A bit louder please
Raise the sound

Lakasan mo ang boses mo
Hindi kita marinig
Palakasin mo pa
Lakasan mo naman
Konting lakas pa
Palakasan mo ang tunog mo
Lakasan mo ang tunog
Dagdagan mo ang lakas ng tunog

## system.volume:down

Make it quieter
Turn it down
Lower the volume
That is too loud
Soften your voice
A bit quieter please
Reduce the sound
Mute the sound
Turn the sound off

Hinaan mo ang boses mo
Masyadong malakas
Pahinaan mo naman
Konting hina naman
Bawasan mo ang lakas
Hinaan mo nga
# Volume is the hardest pair in the bank. An embedding places antonyms
# very close together — they share every word but the polarity verb —
# and "Pahinaan mo ang tunog" initially matched "Palakasan mo ang tunog
# mo" at cosine 0.969, i.e. the model was reading "tunog" and ignoring
# the direction. Both sections therefore carry the same nouns with both
# polarities, so the only thing left to distinguish them is the verb.
Hinaan mo ang tunog
Bawasan mo ang tunog
Pahinaan mo ang tugtog
I-mute mo ang tunog
Patayin mo ang tunog

## system.language:en

Speak in English
Use English please
Change the language to English
English please
Talk to me in English
I want English
Answer me in English

Ingles naman
Sa Ingles ka magsalita
Gawin mong Ingles ang salita
Palitan mo sa Ingles
Ingles na lang sana
Mag-Ingles ka na lang

# "Lumipat ko ng lengwahing English" lost outright to
# `__escalate__:language_mentioned` ("Marunong akong mag-Ingles") in field
# testing. Neither `lumipat` nor `lengwahe`/`wika` appeared anywhere in
# the bank, so the only token the matcher could read was "Ingles" — which
# is precisely the token that bucket exists to neutralise. The switching
# VERB is what separates a request from a remark, so it has to be present
# on this side too.
Lumipat ka sa wikang Ingles
Lumipat ka sa Ingles
Palitan mo ang wika sa Ingles
Ibahin mo ang lengwahe sa Ingles
Gamitin mo ang wikang Ingles
Switch to the English language
Change your language to English

## system.language:tl

Speak in Tagalog
Use Filipino please
Change the language to Tagalog
Talk to me in Filipino
I want Tagalog
Answer me in Filipino

Tagalog naman
Sa Tagalog ka magsalita
Gawin mong Tagalog ang salita
Palitan mo sa Filipino
Filipino na lang sana
Mag-Tagalog ka na lang

# Same switching verbs as the `:en` section — see the note there. Both
# sides carry them so the verb distinguishes request from remark, and the
# language name distinguishes the two directions.
Lumipat ka sa wikang Tagalog
Lumipat ka sa Tagalog
Palitan mo ang wika sa Tagalog
Ibahin mo ang lengwahe sa Filipino
Gamitin mo ang wikang Filipino
Switch to the Tagalog language
Change your language to Filipino

# --------------------------------------------------------------------------
# Escalations. Everything below must reach the LLM. These are not padding —
# each bucket is a class the matcher would otherwise steal, and the whole
# safety argument for the fast path rests on them being here. The navigation
# and place buckets are the ones with open text spans; the rest are
# near-misses that sit close to a real class in embedding space.
# --------------------------------------------------------------------------

## __escalate__:navigation.start

Take me to the mall
Navigate to Robinsons Place
Guide me to the nearest pharmacy
How do I get to the church
Go to the bus terminal
Bring me to my office
Find me the closest convenience store
Walk me to the market
I want to go to the bank
Help me find the bakery

Dalhin mo ako sa palengke
Papuntang simbahan
Gabayan mo ako sa pinakamalapit na botika
Puntahan natin ang opisina
Ihatid mo ako sa bahay
Gusto kong pumunta sa bangko
Tulungan mo akong hanapin ang tindahan

# "Can you help me go home?" — a real field transcript — sat 0.0199 from
# firing `system.help`, i.e. it escalated by one ten-thousandth. Its three
# nearest neighbours were all `system.help` ("How can you help me", "What
# kind of help can you give"), because a destination request phrased as
# "help me ..." shares every word with asking what the device can do.
#
# That is the worst possible confusion on this device — a user asking to
# be taken somewhere, answered with a feature list — and it was being held
# off by rounding. These pull the "help me get to <place>" family firmly
# onto the escalate side, where the LLM can extract the destination.
# The verbatim field transcript ("Can you help me go home") is pointedly
# NOT here. It sat 0.886 from "Can you jump me the time?" — close enough
# to cost that transcript its margin — because "Can you ..." is carrier
# shared with every other class. The family below covers the case on
# content alone, which is both safer for the neighbours and an honest
# test of generalisation rather than a memorised row.
Help me get home
Help me get to the hospital
Help me find my way to the market
Help me walk to the pharmacy
I need help getting to the terminal
I need help getting home

Tulungan mo akong makauwi
Pwede mo ba akong tulungang makarating sa ospital
Tulungan mo ako papuntang palengke
Kailangan ko ng tulong para makarating sa simbahan

## __escalate__:place

Save this spot as my clinic
Remember this location as the bakery
Call this place my office
Forget the place called clinic
Delete the saved place bakery
Store this as my usual stop

I-save mo ito bilang klinika
Tandaan mo itong lugar bilang panaderya
Tawagin mo itong opisina
Burahin mo ang klinika sa listahan
Kalimutan mo na ang panaderya

# Asking about ONE saved place is not `place.list`, and there is no intent
# for it. These sit a short distance from the `place.list` section above —
# both are questions about saved places — so they have to be here
# explicitly or the matcher will read the list intent out of them and
# answer "you have home, the clinic and the bakery" to someone who asked
# a yes/no question about one of them.
Is my home still saved
Do you still have the clinic saved
Did I save the bakery
Where is my home saved
Is the office on my list

Naka-save pa ba ang bahay ko
Nandiyan pa ba ang klinika
Na-save ko ba ang panaderya
Nasaan ang naka-save kong bahay

## __escalate__:volume_level

Set the volume to eighty
Put the volume at fifty percent
Volume forty
Change the volume to seventy
Set it to thirty

Gawin mong walumpu ang volume
Itakda mo sa limampu ang lakas

## __escalate__:other_language

Speak in Spanish
Can you talk in Japanese
Switch to Cebuano
Use Bisaya please
Change the language to Korean

Magsalita ka ng Bisaya
Sa Ilocano ka naman magsalita

## __escalate__:language_mentioned

# A language NAME in an utterance is not a request to switch to it, and
# this was the single biggest source of wrong fast-path answers: "How do
# you say hello in Tagalog" and "I speak Tagalog at home" both matched
# "Speak in Tagalog" above cosine 0.90. The embedding sees the language
# name and the verb "speak" and has no way to notice that one is a
# request and the other is a statement. Only examples fix that.

How do you say goodbye in Spanish
How do you say water in Tagalog
What is the Tagalog word for bread
My family speaks Bisaya at home
I learned English in school
She speaks Filipino very well
Is this written in Tagalog
What language is this sign in
English is hard for me
I am studying Japanese

Paano sabihin ang salamat sa Ingles
Ano ang Tagalog ng bread
Marunong akong mag-Ingles
Nag-aaral ako ng Ingles
Tagalog ba ang nakasulat dito
Anong wika ito
Mahirap ang Ingles para sa akin

I enjoy watching Tagalog movies
My favourite songs are in English
Mahilig ako sa mga kantang Ingles

## __escalate__:other_place

How far is the mall from here
Where is the nearest Jollibee located
What is the address of the hospital
How long does it take to reach Manila
Which street is the pharmacy on

Gaano kalayo ang mall mula dito
Saan ang pinakamalapit na Jollibee
Ano ang address ng ospital
Gaano katagal papuntang Maynila

## __escalate__:near_miss

Help me cross the street
Help me carry this bag
What is the date today
How many days until New Year
Give me a minute
Any time is fine
Be quiet for a moment
Do not talk to me

Tumahimik ka muna
Anong petsa ngayon
Ilang araw na lang bago mag-bagong taon
Sandali lang
Huwag ka munang magsalita

# Look-alikes of answerable classes that mean something else: an alarm is
# not an alert, shutting a door is not shutting down, and "stop talking"
# is not "stop navigating". Each sat within the margin of the wrong class.
Set a timer for five minutes
Wake me up in the morning
Gisingin mo ako mamaya
Close the window
Shut the gate please
Isara mo ang bintana
Stop speaking for a while
Quit talking
Can you recognize faces
Are you able to see in the dark

## __escalate__:chitchat

What is the weather today
Who is the president
Put on some music
Send a message to my brother
Tell me a joke
What is the price of rice
Thank you so much
Alright then
I am feeling tired
The weather is nice
How do you say thank you in Japanese
Call my mother
What is the capital of Thailand

# Whisper hallucinations on silence or background noise. These are not
# things a user says — they are what the STT invents when it hears
# nothing, and they arrive at the parser looking like real transcripts.
# Without them here the matcher has to reject them on score alone, and a
# two-word fragment scores high against almost anything.
Um
Mm hmm
Please subscribe
Thank you for watching
Bye

Ano ang balita ngayon
Sino ang pangulo natin
Magpatugtog ka ng kanta
Magpadala ka ng mensahe
Salamat po
Sige
Pagod na ako
Maganda ang panahon ngayon
Magkano ang bigas
Tawagan mo si nanay

# Statements about the user's own phone or home, not questions about
# this device. They share the device.status vocabulary.
The battery of my phone is almost empty
My cellphone needs charging
Mahina na ang baterya ng cellphone ko
