# Desk Assistant

Two pillars on one Brain running on the user's Mac: Lupin, a desk companion whose Body is a small screen standing on the desk and who can act on the user's Mac and Cowork; and Panels, old devices the user owns turned into desk panels of widgets (ADR 0002).

## Language

### Identity

**Desk Assistant**:
The product: the whole system across the server, the clients (Mac, RG406H handheld, iPhone) and the Electron shell.
_Avoid_: EMO, the app, the assistant (when the product is meant)

**Lupin**:
The one character who lives in the Desk Assistant: a black-and-white cartoon husky with glowing cyan eyes, a white muzzle with a pink nose and a dark collar carrying a cyan sound wave that lights up when he speaks. He is shown as a bust by default and full-body only while performing a Trick. He has a voice, a personality, memory and a Mood.
_Avoid_: EMO, Jarvis, the face, the bot, the assistant (when the character is meant)

**Brain**:
The part of the Desk Assistant that runs on the user's Mac and thinks for Lupin: conversation, memory, Mood, Today, Cowork and Mac control. There is exactly one.
_Avoid_: server, backend (when the role is meant)

**Body**:
A physical device that shows Lupin, plays his sounds and senses the user (touch, voice, buttons); it decides nothing on its own beyond small idle behaviours. The main Body is the ESP32 desk screen. The RG406H and the Mac mini-pet are other Bodies.
_Avoid_: client, device, frontend (when the role is meant)

**Active Body**:
The one Body Lupin lives in right now: the highest-ranked connected Body in the priority list the user sets on the Mac (by default the ESP32, then the RG406H). Lupin is never in two Bodies at once. The user can talk to Lupin from any device, but Lupin always answers in the Active Body; the device the user spoke from only shows the reply as text.

**Dock**:
A control surface for the user's Mac (its Pinned Shortcuts and its open apps), shown as a Dock page on a Panel. The RG406H is the Dock and can also be a Body.
_Avoid_: Stream Deck, control panel

**Panel**:
A device role: a screen that shows the pages of its Layout (widgets) and sends actions by ID. Any old phone, tablet, iPad, laptop or Kindle can be a Panel; it decides nothing on its own.
_Avoid_: dashboard, deck, client

**Device Role**:
What the user chose a connected device to be: Body, Panel, or Body + Panel. Chosen per device; a Body + Panel device shows Lupin as one of its pages.
_Avoid_: mode, device type

**Layout**:
A named set of pages of widgets on a grid (12 × 6, with portrait and landscape variants), assigned to one or more devices. Edited in the Mac editor; a device can only arrange it (move, resize, add, remove widgets).
_Avoid_: dashboard, theme, template (a template is a starting Layout)

**Widget**:
One tile on a Layout page that shows a data source or offers controls (clock, Mac stats, Claude Code sessions, now playing, notes…). Its settings and credentials live on the Mac.
_Avoid_: card, tile, component

**E-ink Mode**:
How a Panel runs on an e-ink device such as the Kindle: black and white, rendered on the Brain, no animation, refreshed every few minutes over HTTP.

### Lupin's inner life

**Expression**:
What Lupin's face shows right now, chosen from a fixed set (happy, sleepy, skeptical…). Short-lived. Drawn as a combination of states of Lupin's layers (head, eyes, eyelids, eyebrows, mouth/tongue, ears, collar), the same on every Body.
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
Anything Lupin asks the Desk Assistant to perform on its behalf during a conversation: a Trick, a Shortcut, a Cowork Task, a Pomodoro start/stop, a tool on an external MCP server.
_Avoid_: tool call, command

**Agent Request**:
Something an outside agent (Claude Code, another MCP client on the Mac) asks Lupin to do through Lupin's local MCP server: say a sentence, show an Expression, read Today, post a Signal. Each carries a risk level; nothing runs outside the existing whitelists. The opposite direction of an Action.
_Avoid_: Action (when an outside agent is the one asking), command

**Signal**:
An event a data source emits that Lupin may react to (Claude Code needs the user, CI failed, a timer ended, a habit is due, a meeting is soon). Lupin reacts with an Expression; he speaks up unprompted only for important Signals, and stays quiet during a Pomodoro except when Claude Code needs the user.
_Avoid_: notification, alert, event (when this is meant)

**Skill**:
A behaviour pack the user switches on to shape how Lupin thinks and talks (e.g. focus coach, coding buddy). A Skill is not an Action.
_Avoid_: ability, plugin

**Trick**:
A physical, audiovisual performance by Lupin (a spin, a dance), with no effect outside the Desk Assistant.
_Avoid_: animation, pet action

**Shortcut**:
A user-configured button that makes the Mac do one thing: a key combo, an app activation, a safe Mac command or a canned prompt.
_Avoid_: tile, macro, hotkey

**Pinned Shortcut**:
A Shortcut the user chose, on the Mac, to show in the Dock. Only Pinned Shortcuts appear there, in the order the user set; Shortcuts are created, edited and pinned only on the Mac.
_Avoid_: deck key, favourite

### Cowork

**Cowork**:
The user's personal workspace outside the Desk Assistant (state files and a catalogue of runnable actions) that the Desk Assistant reads from and writes to.
_Avoid_: Nathan OS

**Cowork Task**:
An operation in Cowork that carries a risk level (read, write, external); anything beyond read needs the user's approval.
_Avoid_: Cowork action, job

**Today**:
The daily summary of the user's day, built from Cowork, the calendar and the inbox, and checked so it never states things those sources don't contain.
_Avoid_: briefing, digest

**Data Consent**:
The user's permission, given on the Mac, for one named LLM provider to see their calendar, their email, the contents of their files or the Mac's front app (its name and window title), one permission for each. It lapses by itself when the provider changes. Without it, calendar, email, file contents and the front app never leave the Mac. A local provider (Ollama) runs on the Mac and needs none.
_Avoid_: privacy setting, sharing

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
One of the two full-screen layouts the user switches between on a device that is both Body and Dock: Pet (Lupin, with a quiet clock, Pomodoro and Now Playing around him) and Dock. The user switches with `L1`/`R1` or a swipe. A device that is only a Dock, because Lupin is in another Active Body, has no Pet Mode. On a device with a Layout, the Modes are its pages: the Pet page (if it is a Body) and the Layout's pages.
_Avoid_: screen, tab, view, Ambient Display

**Settings**:
The area outside the Modes, opened by one discreet button or `Start`, with: Voice and sound, Brain (provider/model, the Mac's address over Wi-Fi/USB), Memory, Skills, Dock (view Shortcuts only; setup stays on the Mac) and Diagnostics (including the Expressions test panel). Pet Mode has no top bar.
_Avoid_: Skills mode, Diagnostics mode

**Presence**:
Lupin being on the desk while the user works, reacting to how long they have worked without a break, the time of day, their voice and touch, and the music playing.
_Avoid_: ambient mode, idle
