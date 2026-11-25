# Brief: Chart PDF and URL data in chat

## Problem Statement
In chat, a user can attach a CSV and ask for a chart (`query_csv` builds a ```chart spec; works today).
They cannot do the same with a PDF or with a link to a CSV/PDF. Add those two sources.

## Users
Logged-in chat users (any agent type). Same permissions as today's chat; no new roles.

## Inputs
- Paperclip attach (`#file-input`): `.csv` (existing) and `.pdf` (new).
- A URL pasted in the message text pointing at a `.csv` or `.pdf` file (new).

## Outputs
- Same chart output as today (```chart block rendered by the page). No change to chart types.
- Clear chat message when it fails (no table found, download blocked, too large, timeout).

## Approach (decided)
Convert at ingestion, reuse the existing CSV pipeline:
1. PDF upload -> extract text-based tables (new dependency, pdfplumber) -> write one CSV -> store it as the message's `file`.
2. URL in message -> safe server-side download -> if CSV store as is; if PDF go through step 1.
3. From there `conversation_file_paths`, `get_csv_columns`, `query_csv` work unchanged.

## Update (user clarification)
Charting must be optional and on demand for a document already uploaded via the "Upload document" button:
the PDF still goes to Temporal/RAG as today, and afterwards the user can ask in chat "make a chart of this document".
So the "Upload document" PDF is also chartable (the earlier "paperclip only" decision becomes "paperclip AND uploaded documents").
Nothing is charted automatically; the Temporal/RAG flow itself is unchanged.
Gap found: `Message` has no link to `rag.Document` (UploadDocumentView only saves the filename as message text),
so the chat cannot tell which document "this document" means.

## Decisions
| Topic | Decision |
|---|---|
| Gap | PDF + URL only; CSV flow untouched |
| PDF type | Text-based tables only (no OCR) |
| PDF entry | Paperclip accepts .csv + .pdf; the "Upload document" (Temporal/RAG) button is untouched |
| Multiple tables | Use the table with the most rows; tell the user it was chosen; merge repeated-header tables only within that rule |
| No table | Tell the user in chat; nothing guessed |
| URL entry | Pasted in message text; no new UI |
| URL meaning | Link to a CSV or PDF file (not HTML pages) |
| URL safety | http/https only; block private/loopback/link-local IPs incl. after redirects; size cap = MAX_CSV_BYTES; 15s timeout; content-type/extension must be csv or pdf |

## Impact check (Django project: Frappe DB-stored customizations do not apply)
| Item | Category | Risk | Note |
|---|---|---|---|
| `chat_page.html:158` `accept=".csv"` | Direct | Low | widen to `.csv,.pdf` |
| `SendMessageView` (views.py:85) | Direct | Medium | add PDF convert + URL detect before `Message.objects.create`; the default "attached X" question text assumes a CSV |
| `consumers.py:65` websocket path | Implicit | Medium | also calls `conversation_file_paths`; URL detection must live in one shared helper or the websocket path behaves differently from HTTP |
| `file_display_name` regex (conversation.py:13) | Implicit | Low | only strips suffix on `.csv`; converted PDFs are stored as `.csv`, so fine |
| `MAX_CSV_BYTES` | Direct | Low | reuse for download cap and converted CSV |
| `UploadDocumentView` / Temporal / RAG | none | none | must not change |
| `chat_uploads/` | Behavioural | Low | already has ~50 duplicate files; no cleanup in scope |
| Existing data | none | none | no model/migration change planned |

Cannot verify from the code: whether any external client posts to `SendMessageView`; whether websocket chat is the main path in production.

## Acceptance Criteria
1. Attach a text-table PDF, ask "chart X by Y" -> chart renders.
2. Paste a public .csv URL + ask for a chart -> chart renders.
3. Paste a public .pdf URL -> same as 1.
4. `http://localhost`, `http://10.x`, a redirect to a private IP, a non-csv/pdf link, >cap size, >15s -> chat message with a clear reason, no crash.
5. PDF without a table -> clear message.
6. Existing CSV attach and "Upload document" PDF flow behave exactly as before.

## Out of Scope
OCR/scanned PDFs, HTML-table pages, JS-rendered pages, new chart types, domain allowlist, cleanup of chat_uploads, changes to RAG/Temporal.

## Constraints
- New dependency: `pdfplumber` (pypdf cannot extract tables). Needs your OK to add to requirements.txt.
- Keep new logic in `chat/service/` (new module for ingestion), thin view changes.
- Code and data rules from memory: you enter any real data yourself.

## Open Questions
- Websocket path (`consumers.py`): does it accept file uploads, or only text? Determines where URL detection must be hooked.
- Where should PDF-extraction failures be surfaced: as an assistant reply (consistent with chat) or HTTP error?
