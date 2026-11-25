# Brief: Temporal run status dialog

## Problem Statement
After sending a document to Temporal, admins cannot see from the Django admin which step the run is at, which steps finished, or why a run failed. They have to open the Temporal UI (localhost:8233) and look it up by workflow id.

## Users
- Staff users of the Django admin (rag app) who can view Documents. Company scoping stays as in `DocumentAdmin.get_queryset` (non-superusers only see their own company's documents).

## Inputs
- `document_id` of a Document row.
- Temporal workflow id `document-<id>` (already used by `rag/temporal/client.py`).

## Outputs
- A new "Run" column on the Document list with a three-dot (⋮) button on rows that have a Temporal run.
- Clicking ⋮ opens a dialog with:
  - Header: workflow id, Temporal `run_id` (UUID), overall run status, start/close time.
  - One row per activity: `claim_document`, `prepare_chunks`, embedding (grouped), `mark_status`, `notify_document`.
  - Per row: status (done / running / pending / failed), attempt count, next retry time (if retrying), start time, end time, duration.
  - Embedding is a grouped summary ("Embedding: 7/10 batches done"), expandable; a failed batch is always shown with its batch range.
  - Error reason (Temporal failure message, and cause if present) on the failed activity.
  - A Refresh button that re-fetches (no polling).
- Friendly messages instead of an error page: "Temporal is unreachable" and "No Temporal run for this document".

## Integrations
| System | Role | Notes |
|---|---|---|
| Temporal server | Source of truth for run id, history, errors | Read-only: `describe` + `fetch_history` via the Python client, live on dialog open |
| Django admin (rag/admin.py) | Hosts the column, JSON endpoint and dialog | New admin URL + view; same `admin_view` / company-scoping pattern |

## Operational
- No new process. Uses the existing Temporal settings (`TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`).
- Dialog fetch is one describe + one history call per click, not per row.
- Errors from Temporal are logged with `logger.exception` and shown as a short message.

## Acceptance Criteria
- A running document shows run id, completed steps as done, current step as running, remaining as pending.
- A completed document shows all steps done with durations.
- A failed document shows the failed step as failed with the error reason and attempt count; later steps (`mark_status`, `notify_document`) still show their own status.
- A retrying activity shows attempt count and the last error.
- A document with no Temporal run shows "No Temporal run for this document".
- With the Temporal server stopped, the dialog shows "Temporal unreachable", not a 500.
- A user cannot open the dialog for a document outside their company.
- The Document list does not slow down (no Temporal call per row).

## Out of Scope
- Storing run id or activity results in our DB (no migration).
- Auto-refresh / polling.
- Run history of older runs for the same document (latest run only).
- Changes to the workflow, activities, worker, Celery or Kafka paths.
- Cancel / retry / terminate buttons.

## Constraints
- Live from Temporal, no schema change.
- Only additive changes in `rag/admin.py` (new column method, new URL/view) plus a new helper module under `rag/temporal/` and a template/JS for the dialog.
- The embedding group is derived from `embed_and_save_batch` events; no change to activity names.
- Follow the existing `process_*_view` / `render_to_string` pattern and the unfold admin theme.

## Impact check
- `rag/admin.py`: `list_display` gains one column; `get_urls` gains one route. No existing column, URL or permission is changed.
- `process_actions` shows `-` for non-pending documents, so the new column must be a separate column. Reusing `process_actions` would hide the ⋮ exactly when a run exists.
- `has_change_permission` is False for Document, so the view must check `has_view_permission` and use `get_queryset` for company scoping.
- Nothing else references `process_actions` or the `rag_document_*` URL names.
- Not verifiable from the code: Temporal's history retention (dev server default is short), so old runs may later show "No Temporal run".

## Open Questions
- Retention: after the namespace retention period, closed runs disappear from Temporal and the dialog will say no run found. Acceptable for dev?
- Documents processed by Celery/Kafka have no run: show no ⋮ at all, or a disabled one?
