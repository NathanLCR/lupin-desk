# Brain↔Body Protocol (version 1)

The **Body** opens a single WebSocket at `/ws` and uses only that to talk to the **Brain** (Lupin). All frames are JSON text. Vocabulary in `GLOSSARY.md`; decision in `docs/adr/0001-companion-first-brain-and-body.md`.

## Body → Brain

| Event | Fields | Description |
|---|---|---|
| `hello` | `body` ("esp32", "rg406h-web", "web"), `protocol` (1), `audio`? (list, e.g. `["m4a"]`), `device_id`? , `name`? , `screen`? | First message. A non-empty `audio` asks for the Brain's voice. The Brain answers `welcome`. `device_id`, `name` and `screen` identify the device (see Devices and Device Roles). |
| `text` | `text` | The user's chat message; starts a turn. |
| `audio` | `data` (base64), `mime_type`, `language`? | Audio recorded for STT; starts a turn. (Not to be confused with the Brain→Body `audio`.) |
| `touch` | `kind` ("pet" \| "poke"), `intensity`? | A touch on Lupin; the Brain answers `mood`. |
| `interrupt` | none | Cancels the active turn (and its audio). |
| `typing` | `active` (bool) | The user is typing; the Brain answers `state`. |
| `clear_history` | none | Clears the short-term history. |
| `subscribe` / `unsubscribe` | `topics` (list of topic names) | Adds or removes data topics. Needs `hello` first. The Brain answers `subscribed`. |
| `action` | `id`, `args`? (object) | Runs a registered Action by ID. The Brain answers `action_result`. |

There are other control messages (shortcuts, approvals, actions) used by the Dock; they are outside this minimal contract.

## Brain → Body

| Event | Fields | Description |
|---|---|---|
| `welcome` | `protocol` (1), `active_body` (null when no Body is connected), `active` (bool), and for a device with a valid `device_id`: `device_id`, `name`, `roles`, `layout_id` | Answer to `hello`: which Body currently has Lupin and whether it is this one, plus the device's Roles and Layout. |
| `role` | `device_id`, `name`, `roles`, `layout_id`, `active` | Sent when the user changes this device's roles, name, Layout or priority on the Mac. No reconnect needed. |
| `subscribed` | `topics` (the device's full list) | Answer to `subscribe`/`unsubscribe`. |
| `topic` | `topic`, `data` | A small JSON push, only to devices subscribed to `topic`. |
| `action_result` | `id`, `ok` (bool), `result`?, `error`? (`unknown_action`, `invalid_args`, `action_failed`) | Answer to `action`. Never echoes `args`. |
| `active_body` | `active_body` (null if none left), `active` (bool) | The Active Body changed (another Body arrived or left, or a role or priority changed). Sent to every connection, Panels included. |
| `state` | `state` (`thinking`, `listening`, `idle`, `error`) | Turn state. |
| `emotion` | `emotion` | The face's current Expression. |
| `mood` | `kind`, `affinity`, `energy`, ... (Mood fields) | Mood after a `touch`. Replaces `companion_updated`. |
| `delta` | `text` | A streamed piece of text. |
| `sentence` | `text`, `first_wake?`, `from_body?` | A complete sentence (the one that will be spoken). `first_wake: true` marks First Wake sentences (the Dock goes up to the Pet with them). `from_body` only appears in mirrored events (see Replies to a Body that is not the Active Body). |
| `audio` | `sentence` (index 0 in the turn), `seq` (0), `last` (bool), `mime` ("audio/mp4"), `data` (base64, up to 24 KiB raw) | The sentence's voice, in chunks. Only sent if `hello` asked for audio and TTS is available. A TTS failure skips the audio without an `error`. |
| `done` | `text`, `emotion`, `facts`, `companion`, `first_wake?` | End of the text turn. The final `audio` events may arrive after it. `first_wake: true` marks the First Wake speech (the first interaction of the day after 5am on the Active Body), which arrives before the reply to the text/audio or right after a touch's `mood`. |
| `interrupted` | none | Turn cancelled; no new `audio` is sent. |
| `error` | `message` | Failure. |

The HTTP `/api/tts` still exists for the Dock and other uses.

## Devices and Device Roles

A device generates a stable ID on first run (`static/device.js`, `DeskDevice.helloFields()`) and sends `device_id` (8-64 chars of `A-Za-z0-9_-`), `name` and `screen` (`width`, `height`, `dpr`, `orientation`, `eink`) in `hello`. The Brain stores the device in the `devices` table (`app/devices.py`): ID, name, roles, `layout_id`, `body_priority`, `last_seen`. A **new device defaults to the Panel role only**; roles are never changed by the device. A `hello` without a valid `device_id` is a legacy Body: roles `["body"]`, nothing stored.

Roles are set on the Mac (the editor UI is P03; the API exists now). Reads are open to any client; writes are Mac-only (403 elsewhere):

- `GET /api/devices` returns `{"devices": [record + connected + active]}`.
- `PUT /api/devices/{id}` takes any of `name`, `roles` (subset of `body`, `panel`, non-empty), `layout_id` (string or null), `body_priority` (int or null). The device gets a `role` message and the Active Body is recomputed live.
- `PUT /api/devices/priority` takes `{"order": [ids]}`: ranks those Bodies 0, 1, 2... and clears the rest.
- `GET /api/actions` lists the registered Action IDs.

## Topics

A device sends `subscribe` with topic names (`^[a-z0-9][a-z0-9_.:-]{0,63}$`, at most 64 per device; others are ignored). Brain code pushes with `DeviceHub.publish(topic, data)` (`app/device_hub.py`); only subscribers receive `topic` messages. The simple rule for Panels is to subscribe to every topic of the whole Layout on connect.

## Actions

`{"type":"action","id":"<action-id>","args":{...}}`. IDs are registered by Brain code in `ActionRegistry` (`app/actions.py`, `app.state.actions.register(id, handler, description)`; IDs match `^[a-z][a-z0-9_.:-]{0,63}$`). Unknown IDs are rejected (`unknown_action`) and logged by ID only, never with `args`. Devices send IDs, never commands: nothing from a device reaches `mac_control` except through a registered handler.

## Access token

On the trusted LAN (ADR 0002) devices connect without `DESK_ACCESS_TOKEN`. The token path stays behind the `DESK_REQUIRE_TOKEN=1` setting (`Settings.require_access_token`, default off).

## Active Body

Lupin lives in one Body at a time, chosen among connections whose roles include `body`. Order: a Body the user ranked with `body_priority` beats unranked ones (lower number first); then the legacy kind rank `esp32` > `rg406h-web` > anything else; then the latest `hello` wins. When the Active Body changes, the other Bodies receive `active_body`. A Body with `active: false` receives no `audio`, does not speak through the browser and stays as a Dock only (no Pet Mode). When the Active Body leaves, the next one in line receives `active_body` with `active: true`.

## Replies to a Body that is not the Active Body

Any Body can ask a question (`text`, `audio`, `run_shortcut` with `agent_prompt`). If the asker is not the Active Body, it receives the usual text events, **without `audio`**. The Active Body (another connection) receives copies of `emotion`, `sentence` and `done`, and the reply's `audio` if it declared audio in `hello` and TTS is available, each with `"from_body": "<Body that asked>"`. `delta`, `state`, `transcript` and `memory_updated` are not mirrored. If the asker is the Active Body, nothing changes. With no Active Body, the asker receives text only. If the Active Body drops mid-turn, mirroring stops without an error and the reply to the asking Body continues.

## Shortcut configuration only on the Mac

`GET /api/client-info` returns `{"is_mac": bool}` (true for loopback or for one of the Mac's own IPs). Creating, editing, deleting, pinning, reordering and restoring Shortcuts (`POST/PUT/DELETE /api/shortcuts...`) return **403** off the Mac, even with `DESK_DEV_NO_TOKEN` (the old `DESK_DEV_SEM_TOKEN` is still accepted as a fallback). Running (`/run` and `run_shortcut`) stays open to any Body. A new Shortcut starts unpinned (`pinned_on_deck = 0`; existing databases are not migrated).

## Data Consent

`GET/PUT /api/data-consent` use `{"calendar": bool, "email": bool}`. Calendar events sent to clients have `title`, `start` and `all_day`; the inbox has `unread` and `recent`, each message with `sender` and `subject`.
