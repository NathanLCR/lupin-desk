# 08 - Image editor

Status: ready-for-agent

## Context

Last feature in the queue (02..08). Lupin helps with simple image edits at the user's request, as an Action. Scope still undefined.

## Scope

- Define which edits are in (crop, resize, remove background, others).
- Define the input (a file on the Mac, the clipboard) and the output.
- Without reintroducing Screen Look or Clipboard Read, removed in 01, unless that is revisited.

## Acceptance criteria

- [ ] Minimum scope defined and approved.
- [ ] Voice or touch flow described.
- [ ] Decided whether it is local or depends on an external provider.
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

- Which edit does the user actually make often?
- How to get the image without Clipboard Read?

## Decisions (grill 2026-11-18)

- The editor is a Panel widget (built on panels P02), plus voice commands through Lupin.
- Input: the user picks or drops a photo on a Panel device; it is uploaded to the Brain (images only, size-capped). Clipboard Read stays removed.
- Edits: crop (touch handles on the Panel), resize, compress, remove background (macOS Vision, local), convert format (HEIC/PNG/JPG/WebP).
- All processing is local (`sips`, Vision). No provider.
- The result downloads back to the device and is saved to `~/Pictures/Lupin` on the Mac.
