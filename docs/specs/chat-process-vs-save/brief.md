# Brief: "process" vs "save" in chat

## Problem Statement
Today an uploaded PDF stays unsaved until the user says "save" (`save_document` tool), and the only save path is Temporal. We want two explicit chat commands:
- **process** – handle the file temporarily via Temporal; no `rag.Document` row; the result lives in the chat message history; charts can be made from it.
- **save** – persist to the `rag.Document` model; the bot asks which method to run it with (Celery / Temporal / Kafka).

## Users
Authenticated chat users (support agent conversations), per company.

## Inputs
- Chat message containing keyword `process` or `save` (keyword detection in `ChatConsumer.receive_json`, before `generate_reply`).
- Source: PDFs, CSVs and URLs.
- For save: user's follow-up reply choosing `celery`, `temporal` or `kafka`.

## Outputs
- process: Temporal workflow output (extracted text/summary) written into the assistant `Message.content`, so follow-ups and charts (`make_chart`) can use it. No `Document` / `DocumentChunk` rows.
- save: `Document` row + run through the chosen method (Temporal: `start_document_processing`; Celery: `process_document_task`; Kafka: `publish_process_request`), live status card as today.

## Integrations
| System | Use |
|---|---|
| Temporal | process (new temp workflow) and save-via-temporal (existing `ProcessDocumentWorkflow`) |
| Celery | save-via-celery (`rag/tasks.py`) |
| Kafka | save-via-kafka (`rag/service/kafka_events.py`) |

## Acceptance Criteria
1. "process" on a PDF/CSV/URL creates no `Document` row; output appears in chat and is usable in later turns and for charts.
2. "save" asks "Celery, Temporal or Kafka?" every time; the next reply picks the method; Document is created and processed via that method.
3. "save" with nothing to save, or "process" twice, returns a clear message, no side effects.

## Out of Scope
Changing embedding/chunking logic; changing Celery/Kafka workers.

## Constraints / Impact (existing code touched)
- `chat/consumers.py` `receive_json` (keyword routing).
- `chat/service/langgraph_agents.py` `save_document`, system prompts (lines ~531, ~813), `read_document_text`.
- `chat/service/documents.py` `register_pdf_for_processing` (Temporal hardcoded; needs method param).
- `chat/service/conversation.py` `conversation_pdfs`/`PendingPdf`.
- `chat/tests.py` references agent tools.
- Needs a pending "awaiting save method" state per conversation (no field exists today).

## Open Questions
- Where to keep the pending save-method state (new Conversation field vs inferred from last assistant message)?
- Exact content of "temporal process output" (text only vs summary).
- URL/CSV have no current save path through Document; define what "save" means for them.
