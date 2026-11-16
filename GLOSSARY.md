# Desk Assistant

A desk companion, Lupin, whose Brain runs on the user's Mac and whose Body is a small screen standing on the desk; he can also act on the user's Mac and Cowork.

## Language

### Identity

**Desk Assistant**:
The product: the whole system across the server, the clients (Mac, RG406H handheld, iPhone) and the Electron shell.
_Avoid_: EMO, the app, the assistant (when the product is meant)

**Lupin**:
The one character who lives in the Desk Assistant: a pet with a face, a voice, a personality, memory and a Mood.
_Avoid_: EMO, Jarvis, the face, the bot, the assistant (when the character is meant)

**Brain**:
The part of the Desk Assistant that runs on the user's Mac and thinks for Lupin: conversation, memory, Mood, Today, Cowork and Mac control. There is exactly one.
_Avoid_: server, backend (when the role is meant)

**Body**:
A physical device that shows Lupin, plays his sounds and senses the user (touch, voice, buttons); it decides nothing on its own beyond small idle behaviours. The main Body is the ESP32 desk screen. The RG406H and the Mac mini-pet are other Bodies.
_Avoid_: client, device, frontend (when the role is meant)

**Active Body**:
The one Body Lupin lives in right now: the ESP32 whenever it is connected, otherwise the RG406H. Lupin is never in two Bodies at once.

**Dock**:
A role a device plays: a control surface for the user's Mac (its open apps and the Shortcuts). The RG406H is the Dock and can also be a Body.
_Avoid_: Stream Deck, control panel

### Lupin's inner life

**Expression**:
What Lupin's face shows right now, chosen from a fixed set (happy, sleepy, skeptical…). Short-lived.
_Avoid_: emotion

**Mood**:
Lupin's persistent internal state, which shifts with interaction and drifts back over time.
_Avoid_: emotion, companion state

**Affinity**:
The part of Mood that measures Lupin's bond with the user; it grows through conversation and petting.

**Energy**:
The part of Mood that measures how awake and lively Lupin is.

### What Lupin can do

**Action**:
Anything Lupin asks the Desk Assistant to perform on its behalf during a conversation: a Trick, a Shortcut, a Cowork Task, a Pomodoro start/stop.
_Avoid_: tool call, command

**Skill**:
A behaviour pack the user switches on to shape how Lupin thinks and talks (e.g. focus coach, coding buddy). A Skill is not an Action.
_Avoid_: ability, plugin

**Trick**:
A physical, audiovisual performance by Lupin (a spin, a dance), with no effect outside the Desk Assistant.
_Avoid_: animation, pet action

**Shortcut**:
A user-configured button that makes the Mac do one thing: a key combo, an app activation, a safe Mac command or a canned prompt.
_Avoid_: tile, macro, hotkey

### Cowork

**Cowork**:
The user's personal workspace outside the Desk Assistant (state files and a catalogue of runnable actions) that the Desk Assistant reads from and writes to.
_Avoid_: Nathan OS

**Cowork Task**:
An operation in Cowork that carries a risk level (read, write, external); anything beyond read needs the user's approval.
_Avoid_: Cowork action, job

**Today**:
The daily summary of the user's day, built from Cowork and checked so it never states things Cowork doesn't contain.
_Avoid_: briefing, digest

**First Wake**:
The user's first interaction with Lupin on the main device after 5am, when Lupin tells the user Today in his own voice.
_Avoid_: morning briefing, first load

**Screen Look**:
Lupin looking at the user's screen on request.
_Avoid_: Jarvis Vision

**Clipboard Read**:
Lupin reading the user's clipboard on request.
_Avoid_: Jarvis Clipboard

### Surfaces

**Mode**:
One of the two full-screen layouts the user switches between on a device that is both Body and Dock: Pet (Lupin, with a quiet clock, Pomodoro and Now Playing around him) and Dock. A device that is only a Dock, because Lupin is in another Active Body, has no Pet Mode.
_Avoid_: screen, tab, view, Ambient Display

**Settings**:
The maintenance area outside the Modes where the user switches Skills on and off and runs diagnostics.
_Avoid_: Skills mode, Diagnostics mode

**Presence**:
Lupin being on the desk while the user works, reacting to how long they have worked without a break, the time of day, their voice and touch, and the music playing.
_Avoid_: ambient mode, idle
