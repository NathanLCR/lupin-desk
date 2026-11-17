# 10 - Lupin's look: layered husky

Status: delivered (first art); final art and ESP32 measurement pending

## Context

Feedback from the RG406H test: the abstract EMO-style face is wrong. Lupin is a black-and-white cartoon husky (reference sent by the user): glowing cyan eyes, two cyan dots above, a thin cyan outline, white muzzle with a pink nose, curled tail, dark collar with a cyan sound wave. Related to 02 (living Body) and 09 (Dock).

## Decisions (grilling, 2026-11-16)

- Bust as the default framing; full body only in Tricks (`dance`, `stretch`, `nap`). `sing`, `meditate` and `celebrate` stay on the bust with effects. The collar wave lights up when Lupin speaks.
- Layered animation (head, eyes, eyelids, eyebrows, mouth/tongue, ears, collar, cyan dots), identical on web and LVGL.
- Art: first version as simple vector SVG made by me; the final art arrives later through the same layer format.
- Format: one SVG per layer is the single source; a script generates 480x320 PNGs with transparency for the ESP32.
- A single `expressions -> layer states` table shared by both Bodies (12 Expressions). Blinking and looking around belong to the Body.
- ESP32 budget: PNG per layer up to ~20 KB, bust ~320x300, 8-bit indexed colors, up to ~24 layers, full body in 3 sets of frames loaded only during the Trick. Measure when the board arrives.
- Palette: black background, cyan as the only accent and only on Lupin; the rest of the interface in dark neutrals with white text, no glow on buttons, no emoji.

- Delivered after the bar and Settings (issue 02). The old EMO face is removed when the husky lands, with no fallback.

## Acceptance criteria

- [x] Husky SVG layers and the expressions -> layers table (`static/lupin/`).
- [x] The web face draws the husky by layers and covers the 12 Expressions (`static/lupin.js`; EMO face removed).
- [x] The collar wave lights up when speaking.
- [x] 3 full-body Tricks (`dance`, `stretch`, `nap`, 2 frames each).
- [x] Script that generates the ESP32 PNGs within budget (`scripts/generate_lupin_png.py`; largest PNG 8.4 KB).

## Delivered (2026-11-17)

- 34 layer variants across 7 layers, plus 6 full-body frames. Total of the indexed PNGs: 86 KB.
- The art is a first simple vector version; the final art arrives by swapping the SVGs, with no code changes.
- Pending: the budget said up to ~24 layers, and there are 34 variants (only 7 show at the same time). Decide with the on-board measurement whether that is a problem.
- Pending: `setAccessory` only records the value; the headphones and Pomodoro art on the face doesn't exist yet. Weather, sweat and yawn from the old face were not ported.
- No physical screen: the husky was only seen in the browser (960x720), not on the RG406H.

## Recraft art (2026-11-17)

- The head, mask, nose, ears, chest and collar now come from the SVG trace generated in Recraft (symmetric husky, front view), split into layers using the same format as before. The `expressions.json` table did not change its contract.
- Only the neutral pose SVG existed. Eyes, eyebrows and mouths for the other expressions were redrawn by hand in the style of the trace. The Recraft PNGs for happy, surprised and hearts did not become SVG; if those SVGs are exported, the variants can be swapped.
- The 6 full-body frames reuse the new head on a simple body that is still hand-drawn.
- Palette: cyan `#11c3fb`, white `#ebebea`, gray `#d6d5d5`, pink `#eb617e`, black. Largest PNG: 8 KB.

## Final art in whole poses (2026-11-17)

- The new art (bust + 7 expressions + 3 full-body Tricks, traced as SVG) replaces the first piecewise version. It comes as complete poses; eyes and mouth can't be separated without redoing the trace.
- Current model: a `pose` layer (8 bust variants) + a `collar` layer (wave glow, lit only when speaking). The `expressions.json` table (version 2) picks the pose by Expression and State.
- Speaking: the collar lights up and the pose alternates between neutral and happy (open mouth) from the audio level (`speech.threshold`).
- Blinking: the table has `blink` (pose → closed-eyes pose), currently empty. The neutral bust SVG with closed eyes is missing.
- No pose of their own: `curious` (tilted neutral), `skeptical` and `sad` (use sleepy). SVGs for curious, skeptical and sad are missing.
- The `dance` Trick uses the wave frames. Total: 16 SVGs, largest PNG 11 KB, 136 KB for the set, well under the ESP32 budget.

## Missing poses (2026-11-17)

- 4 new SVGs arrived (same VTracer trace, no named groups): closed eyes, curious, skeptical and sad. The other 14 files in the batch were identical to those already in use.
- The `pose` layer goes to 12 variants: `blink`, `curious`, `skeptical`, `sad` come in. `blink` = `neutral → blink`; `curious`, `skeptical` and `sad` get their own pose (no extra tilt, the art already comes tilted).
- The common bust framing did not change (`-263.5 -8 1551 1034`), so the collar glow and the bodies stay as they were.
- Total: 20 SVGs, largest PNG 11.3 KB, 171 KB for the set.
- Still missing: dance frames (`dance` still uses wave) and speaking mouths (middle/open); speech still alternates neutral/happy.
