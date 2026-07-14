---
description: Capture a one-line idea, task, or note into the local notebook outside the planning store, with confirm-first graduation to a gap or brainstorm. Does not write to the planning store directly or replace /sw-feedback gap-capture.
alwaysApply: false
---

# `/sw-note`

Low-ceremony capture for things worth remembering that are not yet worth a planning-store artifact. Lives
under `.cursor/sw-notebook/` — deliberately outside `docs/planning/` and the issue-store, so jotting a note
never touches freeze/currency machinery.

## Scope

- Input: `/sw-note <text>` (auto-classified idea/task/note), or explicit `/sw-note task <text>`,
  `/sw-note idea <text>`, `/sw-note note <text>`, each with optional `#tag` tokens.
- Output: one notebook item written to `.cursor/sw-notebook/notebook.jsonl`.
- Does **not** write to the planning store, gap backlog, or a brainstorm doc directly — graduation is a
  separate, confirmed step (see **Graduate**).

## Shapes

| Shape | Meaning | Lifecycle |
| --- | --- | --- |
| `idea` | A rough idea not yet worth a brainstorm | Open until graduated or dismissed |
| `task` | A small actionable reminder | `open` → `done` (via `/sw-note done <id>`) |
| `note` | A plain fact/observation worth remembering | Open indefinitely; no done state |

Tags are free-form `#tag` tokens parsed from the input text; stored as a `tags[]` array.

## Storage

```json
{
  "id": "<uuid or timestamp-slug>",
  "shape": "idea | task | note",
  "text": "<one line>",
  "tags": [],
  "status": "open | done",
  "createdAt": "ISO-8601",
  "doneAt": null,
  "graduatedTo": null,
  "graduatedAt": null
}
```

One JSON object per line, appended to `.cursor/sw-notebook/notebook.jsonl`. Never committed — add
`.cursor/sw-notebook/` to `.gitignore` on first write if not already present (this is operator-local
scratch, not a planning artifact).

## Procedure

1. **Classify** — explicit shape keyword wins; otherwise infer from phrasing (imperative → `task`,
   speculative/"what if" → `idea`, declarative fact → `note`). Ambiguous inference defaults to `note` (the
   most inert shape) and says so.
2. **Redact** — pipe the text through `python3 scripts/memory-redact.py` before writing (same chokepoint as
   every other Shipwright persist path).
3. **Append** — write the JSON line; report the assigned id.
4. **Task-done lifecycle** — `/sw-note done <id>` sets `status: done`, `doneAt: <now>`. Done tasks remain in
   the file (never deleted) for provenance.
5. **At most one deferral-language offer per turn** — if the *user's own chat message* (not the note text)
   contains deferral language ("later", "not now", "someday", "remind me") and no note was already offered
   this turn, offer once: "want me to capture that as a note?" Never offer a second time in the same turn even
   if multiple deferral phrases appear — one ignorable offer, then move on.

## Graduate (confirm-first, bidirectional provenance)

`/sw-note graduate <id> --to gap|brainstorm` promotes a notebook item into a real planning artifact:

1. **Confirm-first** — always show the item and the target artifact type; require explicit `proceed` before
   any planning-store or brainstorm-doc write. Never auto-graduate.
2. On confirm:
   - `--to gap` → `python3 scripts/planning_gap_capture.py <repo> capture --signal-id notebook:<id> --title "<text>"`
   - `--to brainstorm` → hand off to `/sw-brainstorm` with the note text as the seed input (does not write the
     brainstorm doc itself — `/sw-brainstorm` owns that).
3. **Bidirectional provenance** — on successful graduation:
   - Notebook item: set `graduatedTo: <gap-unit-id | brainstorm-path>` and `graduatedAt: <now>`.
   - Target artifact: record a back-pointer to the notebook item id (e.g. a `notebookRef: <id>` line in the
     gap unit body, or a note in the brainstorm doc's Key Decisions when seeded from a notebook item) so
     either side can be traced from the other.
4. Graduated items are never deleted from the notebook — they remain as closed-with-provenance history.

## Session-start index injection (opt-in, redact-or-skip)

Gated by `notebook.sessionIndex` (default **false**). When enabled, session start distills the **open**
notebook items (not `done`/graduated) into a short index and injects it:

1. Build the distilled index (id, shape, one-line text, tags — no full bodies beyond the one line already
   stored).
2. Pipe the distilled index through `python3 scripts/memory-redact.py`.
3. **On redact success** — inject the redacted index.
4. **On redact failure (any non-zero exit)** — skip injection entirely for this session. Never inject the
   raw, unredacted index as a fallback.

**Communication intensity:** lite

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-note`.

## Guardrails

- Never writes to `docs/planning/`, the issue-store, or `GAP-BACKLOG.md` directly — only `graduate` does,
  and only after confirm.
- Redaction chokepoint applies to every write, including the session-start index.
- At most one deferral-language offer per turn — never nags.
- Graduated and done items are retained, never deleted — the notebook is an append-mostly log.
