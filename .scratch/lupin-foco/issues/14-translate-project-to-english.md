# 14 - Translate the project to English

Status: done

## Context

Decided on 2026-11-17: code, comments, identifiers, UI text, commits, docs, issues and README are in English (see `AGENTS.md`). Everything written so far is in Brazilian Portuguese. The user chose to translate it all now, before 03's week of daily use closes. What Lupin *says* stays in Brazilian Portuguese until issue 15 makes it a setting.

## Scope

- Comments, docstrings, identifiers (functions, variables, classes, files), test names and test files.
- UI text in `static/` (labels, buttons, Settings, toasts).
- API/JSON field names (e.g. `nao_lidos` → `unread`, `recentes` → `recent`). The web Body and the Electron shell are updated in the same change, so nothing breaks.
- The Brain↔Body protocol doc and its field names; `docs/protocolo-cerebro-corpo.md` is renamed to `docs/brain-body-protocol.md`.
- Issues 01–13 and `spec.md` in `.scratch/lupin-foco/`, and other docs (`docs/pesquisa-de-mercado.md`, renamed to `docs/market-research.md`, included).
- Values already saved in `data/memory.db` (meta keys, settings) keep working: read the old key as a fallback or migrate it once on startup.

## Out of scope

- What Lupin says: First Wake sentences, the system prompt's reply language, canned replies. They stay Brazilian Portuguese, gathered in one place so issue 15 can add English.
- Behaviour changes of any kind. This is a pure translation and refactor.
- `.scratch/reviews/` (not ours).

## Acceptance criteria

- [ ] No Portuguese left in code, comments, identifiers, UI or docs, except Lupin's spoken strings and user data.
- [ ] All Python and frontend tests pass (same counts as before; the known mini-pet failure may stay).
- [ ] The server starts, and the RG406H web Body and the Mac work as before (live check).
- [ ] An existing `data/memory.db` keeps its saved settings and Data Consent after the change.
