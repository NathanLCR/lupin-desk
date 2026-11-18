# P02 - Panel web runtime, Layouts and widget framework

Status: done (device test pending)
Blocked by: P01

## Scope

- The Brain serves the Panel web app. It must run on old engines: Android 7 WebView/Chrome (Moto G5), old iOS Safari. Plain JS, no build step required by the device; avoid syntax newer than what those engines run (test the oldest).
- Layout model (sqlite + JSON): Layout → pages → widgets placed on a 12 × 6 grid (x, y, w, h), with a portrait and a landscape variant. Templates are starting Layouts.
- Pages: swipe, page dots, and the RG406H's `L1`/`R1`; volume keys where the shell allows. A Body + Panel device shows Lupin's Pet page as one page.
- Widget framework: a registry where each widget declares its ID, sizes it supports, data topics, actions, and a render function. Widgets fail alone (an error shows inside the widget, never breaks the page).
- On-device arranging: long-press enters arrange; move, resize, remove, add a widget from the registry list. Saves back to the Layout on the Brain. Widget settings are not editable on the device.
- Safe-area insets on iOS; keep-screen-on handled by the shell (P04) or Wake Lock where available.
- Ship one starter template so P02 can be tested before widget issues land: clock + a placeholder widget.

## Acceptance criteria

- [ ] The same Layout renders on the RG406H, the Moto G5 (browser), an iPad and a laptop.
- [ ] Rotating a device switches between portrait and landscape variants.
- [ ] Arranging on a device persists and shows up in the Mac editor.
- [ ] A widget that throws shows an error tile; the page keeps working.
- [ ] Frontend tests cover layout math, the registry and arranging.
