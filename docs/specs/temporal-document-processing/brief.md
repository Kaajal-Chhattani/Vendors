# Brief: Temporal document processing

## Problem Statement
Document processing (chunk + embed) runs as a single Celery task / admin request / Kafka message. A crash or a failed embedding call part-way loses the work: the document is left in `started` forever (the hourly job only picks up `pending`) and may keep partial chunks. There is no visibility into how far a document got.

## Users
- Admin users who upload documents and trigger processing in the Django admin (rag app).
- Chat users who receive the "document processed / failed" notification.

## Inputs
- `document_id` of a `Document` with status `pending`.
- `Document.raw_text`, split into 1000-character chunks (same size as `DocumentProcessor.chunk_size`).

## Outputs
- `DocumentChunk` rows with embeddings for the document.
- `Document.status` set to `processed` or `error`.
- Chat notification via the existing `notify_document_processed`.
- Workflow run visible in the Temporal UI.

## Integrations
| System | Role | Notes |
|---|---|---|
| Temporal (dev server, local docker-compose) | Workflow engine | New `docker-compose.temporal.yml`, server on 7233, UI on 8233 |
| Postgres / pgvector | Chunk + status storage | Existing models, no schema change |
| Embedding (`rag.service.embedding.get_embedding`) | Per-chunk embedding | Called from activities |
| Channels / Redis | Chat notification | Existing `notify_document_processed` |
| Celery, Kafka | Existing paths | Left untouched |

## Operational
- New process: `python manage.py run_temporal_worker` (Python SDK `temporalio`, task queue `documents`). Must run alongside daphne, Celery and Kafka workers.
- Config via `.env` / `settings.py` with `config()`: Temporal address, namespace, task queue.
- Logs: standard logging in activities; failures also visible in the Temporal UI.

## Workflow design
`ProcessDocumentWorkflow(document_id)`, workflow id `document-<id>`:
1. `claim_document`: `pending` -> `started`; stop if it was not pending.
2. `prepare_chunks`: delete any existing chunks for the document, return the chunk count.
3. `embed_and_save_batch` per batch of N chunks (N = 20): each batch retried independently, safe to repeat (`update_or_create` on `(document, chunk_index)`).
4. `mark_status`: `processed`, or `error` if retries are exhausted.
5. `notify_document_processed`: always runs, on success and failure.
Activities pass only ids and counts, never model objects or full text.

## Acceptance Criteria
- Happy path: a pending document ends `processed`, with the expected chunks, one notification, workflow Completed in the UI.
- Killing the worker mid-run, then restarting it, completes the document without redoing finished batches and without duplicate chunks.
- A temporary embedding/DB failure is retried and the document still ends `processed`.
- A permanent failure ends the document as `error`, sends the failure notification once, and leaves no stuck `started` status.
- Starting the workflow twice for the same document does not run two copies.

## Out of Scope
- Chat reply workflow (consumer / langgraph).
- Moving the hourly `process_documents_task` beat job to a Temporal schedule.
- Removing or changing the Celery, Kafka or direct admin processing paths.
- `DocumentProcessor` refactoring.
- Production Temporal deployment.

## Constraints
- No migration: duplicates on retry are avoided by deleting existing chunks first (decided), not by a unique constraint.
- Do not modify `DocumentProcessor`, existing Celery tasks, Kafka code or `notify_document_processed`.
- One additive admin action ("Process with Temporal") in `rag/admin.py`, following the existing `process_*_view` pattern.
- Python / Django style of the surrounding code; activities are sync and use the ORM.

## Impact check
Touches existing code only in: `rag/admin.py` (new action + URL), `requirements.txt` (`temporalio`), `settings.py` (new settings), `.env`. It reuses `notify_document_processed` unchanged. No existing field, model or schema changes.

## Open Questions
- Batch size (20) and retry limits/timeouts are initial guesses; tune after trying a large document.
- A document stuck in `started` from before this change is not recovered by this workflow (it only claims `pending`).
- Whether to move the hourly job to Temporal later.
