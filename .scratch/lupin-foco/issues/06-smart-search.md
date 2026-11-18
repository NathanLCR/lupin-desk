# 06 - Smart search

Status: done (live voice check and 1-week use pending)

## Context

Inspired by Taby (smart search): the user asks by voice and Lupin finds things on the Mac and in Cowork and answers. Comes after 05.

## Scope

- Ask by voice and get a spoken answer from Lupin.
- Define the search sources (Mac files, Cowork, notes).
- Read-only.

## Acceptance criteria

- [ ] Search sources and limits defined and documented.
- [ ] No data goes to a provider the user didn't explicitly choose.
- [ ] Answers don't claim what the sources don't contain.
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

- Which sources come first?
- Local indexing or on-demand lookup?

## Decisions (grill 2026-11-18)

- Sources: the notes/tasks store (05), Lupin's memory, Cowork state files (read-only), and Mac files through Spotlight (`mdfind`, whitelisted folders, read-only). No web search.
- On-demand lookup at question time; no index of our own.
- File contents reach the LLM only with a new third Data Consent (files). Without it, Lupin answers with file names and paths only.
- Answers don't claim what the sources don't contain.
