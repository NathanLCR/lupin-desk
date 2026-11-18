# 03 - Morning: First Wake

Status: in progress (Calendar, Inbox and Data Consent done; real use pending)

## Context

First Wake is the user's first interaction with Lupin on the main device after 5am. At that moment Lupin SPEAKS Today, in his own voice. Depends on 02.

## Scope

- Detect the First Wake (first interaction after 5am on the Active Body).
- Lupin speaks Today in 2 to 3 sentences.
- Include Calendar (via Calendar.app) and Inbox (via Mail.app), both read-only.
- Email and calendar data only go to the LLM provider the user explicitly chose.
- Today stays checked so it doesn't claim anything Cowork doesn't contain.

## Acceptance criteria

- [x] The first interaction after 5am triggers First Wake exactly once per day.
- [x] The speech is 2 to 3 sentences and comes out in Lupin's voice.
- [x] Calendar and Inbox are read without any write (fixed `osascript` scripts, read-only).
- [x] Without an explicit provider choice (Data Consent), no email/calendar data leaves the machine.
- [ ] Today invents nothing outside Cowork, Calendar and Inbox.
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

Answered in the spec for the rest of 03 (below): the provider is confirmed by Data Consent, and Inbox comes from Mail.app, with no OAuth and no stored password.

## Spec for the rest of 03 (agreed on 2026-11-17)

### Inbox

- Source: Mail.app, through a fixed read-only `osascript` script, following the same pattern as Calendar (`subprocess.run` with argv, nothing coming from the client). No OAuth, no stored password.
- "Unread" = every unread message in the inbox of all Mail.app accounts (the number on Mail's badge).
- If Mail.app can't be read (no permission, closed, error), the email is simply omitted.

### First Wake

- Still no LLM.
- Sentence 1 gains the unread count: "Bom dia! Você tem 4 tarefas abertas e 12 e-mails não lidos." (Good morning! You have 4 open tasks and 12 unread emails.)
- Never speaks the sender or the subject.
- Without a Mail.app read, the sentence stays as it is today.

### Data Consent

- Two switches: one for the calendar, one for the email.
- They live in Settings → Brain and can only be changed on the Mac (`is_mac_client`); other devices only see the state. A change coming from another client gets 403.
- The text names who receives the data, for example: "Permitir que Proxy Local (127.0.0.1:31415) veja sua agenda" (Allow Proxy Local (127.0.0.1:31415) to see your calendar).
- The consent is tied to the provider id and the host of the base_url. If either changes, both switches turn off on their own.
- No exceptions, Ollama included.
- Default: off.

### Conversation

- With calendar consent: the LLM context receives today's calendar (time and title).
- With email consent: it receives the unread messages from the last 24h, at most 10, sender and subject only, never the body.
- Without consent: the context receives none of this, and Lupin says he can't see the calendar/email instead of guessing.
- Calendar and email don't enter the saved history or any log.

### Extra acceptance criteria

- [x] First Wake speaks the unread count without sender or subject.
- [x] Without Data Consent, no calendar/email data appears in the LLM call (test).
- [x] Changing the provider or base_url turns both consents off (test).
- [x] Changing consent from outside the Mac returns 403 (test).

## Done on 2026-11-17

- Trigger on `/ws`: the first touch, text or audio from the Active Body after 5am triggers First Wake. The day is marked before speaking, so it doesn't repeat even if the connection drops. A Body that isn't the Active Body doesn't trigger it and doesn't spend the day's First Wake.
- Order: on touch, the `mood` goes out first and First Wake follows. On text/audio, First Wake speaks first and the turn's reply comes after.
- The speech (`compose_first_wake_speech` in `app/today.py`) is built without an LLM: greeting + open tasks, today's calendar (up to 3 items, "e mais N" / "and N more") and the priority (the task due today, otherwise the first open one). It doesn't enter the history, so the calendar and Cowork don't go to the LLM provider.
- The protocol gained `first_wake: true` on the `done` of that speech. The voice goes through the same server `audio` when the Body asked for audio.
- Calendar: `MacController.read_today_calendar` runs a fixed `osascript` script (read-only, no client input). If macOS denies access to Calendar, the speech just omits the calendar.
- The old card (`/api/first-wake`, the card in Pet Mode and "Ouvir resumo" (Listen to summary) in the browser) is gone.

## Done (rest) on 2026-11-17

- Inbox: `MacController.read_inbox()` runs a fixed Mail.app script (read-only) and returns the unread count of the inbox across all accounts and up to 10 unread messages from the last 24h (sender and subject, never the body). So it doesn't hang on a large mailbox, it looks only at the 300 newest messages; the badge count is exact. A read failure omits the email.
- First Wake: sentence 1 gains "e N e-mails não lidos" (and N unread emails; singular, zero and no-Cowork handled), with no sender or subject and no LLM.
- Data Consent (`app/consent.py`): `GET /api/data-consent` (any client) and `PUT /api/data-consent` (Mac only, 403 elsewhere). Two switches, off by default, tied to the provider id and the host:port of the base_url; any change turns both off, and going back to the old one does not re-enable them. The API key never appears. UI in Settings > Brain, with the receiver's name in the text.
- Conversation: the LLM turn receives an ephemeral `personal_context`. With consent, today's calendar and the unread messages (sender and subject); without it, just an instruction that Lupin has no access and should say so; a read that failed becomes a notice with no data. None of this enters the saved history or any log.
- Tests no longer read the real Mail.app or Calendar (`tests/conftest.py`).
- Known limit: the model's reply is saved in the history as usual; if it quotes a calendar title or a sender, that gets saved.

Still missing:

- The Calendar script doesn't expand recurring events or events that started before today; see in real use whether that bothers.
- 1 week of real use.

## Decisions after delivery (2026-11-17)

- Mail.app latency: with email consent on, every turn reads Mail.app (~6 s), and First Wake waits ~6 s. Left as is on purpose; revisit only if it bothers in daily use.
- History: the injected calendar/email context is never saved, but Lupin's reply is saved as usual, even when it mentions an event or a sender. Accepted: the reply is what the user asked for.
