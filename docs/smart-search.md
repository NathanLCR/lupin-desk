# Smart search

Lupin can answer "what do I have about X?" by searching your data on demand. The
search is read-only and has no index of its own.

## Sources

Searched in this order: tasks and notes (the local store), Lupin's memory, Cowork state
files (read only), and Mac files found with Spotlight (`mdfind`) in `~/Documents`,
`~/Desktop` and `~/Downloads`.

## Limits

- Read only. Nothing is created, changed or deleted.
- On demand. Each question runs a fresh search. There is no index or background crawl.
- Excluded from files: hidden entries (including `.env*`), `Library`, `node_modules`,
  `certs`, and `.pem`, `.key` and `.p12` files.
- At most 5 file results, with a 5 second timeout per folder.
- Text snippets are read only from small plain-text files (such as `.txt`, `.md`, `.csv`,
  `.json`, `.py`). No file is read beyond 1 MB.
- No web search.

## Files Data Consent

Reading file contents with the LLM is a third consent, separate from calendar and e-mail.

- Without it, Lupin mentions only file names and says so.
- With it, Lupin may speak one short line from the first matching file.
- Local Ollama on this Mac needs no consent, because the data stays on the Mac.
- The consent is tied to the active provider and host. Changing either turns it off.

## Answers

Lupin answers only from what the search found. If nothing matches, it says so. It never
claims a file or note that was not found, and it never speaks file contents without consent.
