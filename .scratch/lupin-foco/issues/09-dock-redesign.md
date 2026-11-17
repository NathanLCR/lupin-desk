# 09 - Dock redesign

Status: ready-for-agent

## Context

The Dock is the control surface for the Mac. Today the RG406H is Body and Dock at the same time (Pet and Dock Modes). When the ESP32 arrives, it becomes the Active Body and the RG406H is only Dock. This issue covers both cases and was settled in a grilling session on 2026-11-17 (see `GLOSSARY.md`: Dock, Pinned Shortcut, Active Body, Mode).

## Spec

### Grid and pages

- Dock Mode shows a fixed 3x3 grid with only the Pinned Shortcuts (`pinned_on_deck = 1`), in `sort_order`.
- The grid is paginated. The last page is "Apps abertos" (Open apps: the list of the Mac's apps); it is not a new Mode.
- `L1`/`R1` and the horizontal swipe switch Mode (as today). `L2`/`R2` and the vertical swipe switch page. Page dots sit at the bottom. The D-pad moves focus inside the grid.
- Leaving the Dock: the category tabs, the "Keys: Default/Large" button and the New/Edit/Manage buttons.
- With no Pinned Shortcuts, the first page says "Nenhum atalho fixado. Escolha os atalhos no Mac." (No pinned shortcuts. Choose shortcuts on the Mac.) The "Apps abertos" page keeps working.

### Configuration only on the Mac

- "The Mac" is the client running on the machine itself (loopback: the Mac's browser or Electron).
- There, Settings → Dock has the Shortcuts editor: create, edit, delete, pin/unpin and reorder.
- On any other device, Settings → Dock only lists the Shortcuts, with no editing.
- The server refuses to create, edit, delete, pin and reorder Shortcuts when the client is not loopback (403), even in dev mode with no token.
- A new Shortcut starts unpinned (`pinned_on_deck = 0`). Existing Shortcuts stay as they are (no migration).

### Confirmation

- A Shortcut with `requires_confirmation` asks "Executar?" (Run?) on the device where it was tapped, even if that device is only Dock.

### Dock corner

- On the Active Body, the Dock Mode corner shows a small Lupin. Tapping it goes to Pet Mode.
- On a device that is not the Active Body, the corner shows the "Falar com Lupin" (Talk to Lupin) button: holding it (or `Y`) speaks through the device's microphone; tapping it opens the keyboard to type.
- The Mac mini-pet follows the same rule: off the Active Body, Lupin's drawing disappears and only the button remains.

### Lupin's replies

- Any device can talk to Lupin. Lupin always answers on the Active Body (voice, face, Expression). The device the speech came from receives only the text, on one line, with no audio. With no Active Body connected, the device that asked receives only the text.
- Long speech = the reply reaches the 3rd sentence. First Wake always counts as long speech.
- On the Active Body in Dock Mode:
  - short speech (1 or 2 sentences): the small Lupin speaks (collar lit, mouth moving) and the text appears on one line beside him, cut with "…", and disappears 4 s after the audio ends. The grid doesn't move or get covered.
  - long speech: the screen goes to Pet Mode. If that switch was automatic and the user touched nothing, the screen returns to the Dock 5 s after the audio ends. If the user switched to Pet on their own, it stays on Pet.

## Acceptance criteria

- [x] The grid is a fixed 3x3, paginated, and shows only the Pinned Shortcuts in the Mac's order.
- [x] The open apps list is the last page of the Dock.
- [x] `L1`/`R1` and horizontal swipe switch Mode; `L2`/`R2` and vertical swipe switch page.
- [x] There is no Shortcut editing outside the Mac, neither through the UI nor through the API (403).
- [x] A new Shortcut starts unpinned.
- [x] The small Lupin appears in the corner only on the Active Body; off it, the "Falar com Lupin" button appears.
- [x] Speaking from any device makes Lupin answer on the Active Body, and the originating device shows the text.
- [x] Short speech stays on the Dock with the small Lupin; long speech (3rd sentence or First Wake) goes to Pet and returns on its own if the switch was automatic.
- [x] The toggle between Pet and Dock works both ways. (Pet -> Dock by L1/R1/swipe; Dock -> Pet also by tapping the small Lupin.)

## Done on 2026-11-17

- Backend: `GET /api/client-info`; Shortcut writes (incl. `reset-defaults`) only from the Mac (403 elsewhere); a new Shortcut starts unpinned; reply to a device that isn't the Active Body (text to the asker, `emotion`/`sentence`/`done`/`audio` mirrored to the Active Body with `from_body`); `first_wake: true` on every `sentence` of First Wake. Documented in `docs/brain-body-protocol.md`.
- Dock: 3x3 grid of Pinned Shortcuts ordered by `sort_order`, 9 per page, last page "Apps abertos", page dots, empty state "Nenhum atalho fixado. Escolha os atalhos no Mac.". No tabs, size button, or New/Edit/Manage.
- Controls: `L1`/`R1` and horizontal swipe switch Mode; `L2`/`R2` and vertical swipe switch page (only in the Dock; elsewhere `L2`/`R2` remain Push-to-Talk); the D-pad walks the grid (up/down jump a row).
- Settings > Dock: on the Mac, the full editor (new, edit, delete, pin/unpin, reorder, through the existing modal); on other devices, a read-only list.
- Corner: small Lupin (same face, shrunk by CSS) on the Active Body, a tap opens Pet; on the others, the "Falar com Lupin" button (hold records, tap opens text). Holding `Y` also records in the Dock.
- Speech in the Dock: 1-2 sentences stay in the Dock with a one-line strip (gone after 4 s); the 3rd sentence or `first_wake` goes up to Pet and returns 5 s after the speech only if the switch was automatic; any user input cancels the return. A device that isn't the Active Body shows only text.
- Mini-pet (Electron): off the Active Body it hides the drawing and shows only "Falar com Lupin".
- Tests: Python `tests/test_dock_redesign.py`; frontend `tests/frontend/dock.test.cjs` (shared harness in `harness.cjs`).

Pending / to check by hand:
- Real codes of `L2`/`R2` and `Y` on the RG406H (the code assumes buttons 6/7 and 3 of the standard mapping).
- Layout of the corner and the grid on the RG406H screen and on the iPhone; vertical swipe on real touch.
- In the mini-pet, "Falar com Lupin" only opens the panel (the mini-pet has no WebSocket of its own).
- Old databases keep `pinned_on_deck` as it was (no migration).
