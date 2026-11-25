from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError

with workflow.unsafe.imports_passed_through():
    from rag.temporal.activities import (
        claim_document,
        embed_and_save_batch,
        extract_pdf_text,
        mark_status,
        notify_document,
        prepare_chunks,
        preview_embed_batch,
        split_text_preview,
    )

BATCH_SIZE = 20

DB_TIMEOUT = timedelta(minutes=1)
EMBED_TIMEOUT = timedelta(minutes=5)
EMBED_HEARTBEAT_TIMEOUT = timedelta(seconds=30)

DB_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=5,
)
EMBED_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=5,
)


@workflow.defn
class ProcessDocumentWorkflow:
    @workflow.run
    async def run(self, document_id: int) -> str:
        claimed = await workflow.execute_activity(
            claim_document, document_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=DB_RETRY
        )
        if not claimed:
            return "skipped"

        status = "processed"
        try:
            chunk_count = await workflow.execute_activity(
                prepare_chunks, document_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=DB_RETRY
            )
            for start in range(0, chunk_count, BATCH_SIZE):
                await workflow.execute_activity(
                    embed_and_save_batch,
                    args=[document_id, start, min(start + BATCH_SIZE, chunk_count)],
                    start_to_close_timeout=EMBED_TIMEOUT,
                    heartbeat_timeout=EMBED_HEARTBEAT_TIMEOUT,
                    retry_policy=EMBED_RETRY,
                )
        except ActivityError as error:
            if isinstance(error.cause, CancelledError):
                raise  # stopped from the admin: leave the status to the stop action, don't mark an error
            status = "error"

        await workflow.execute_activity(
            mark_status, args=[document_id, status], start_to_close_timeout=DB_TIMEOUT, retry_policy=DB_RETRY
        )
        await workflow.execute_activity(
            notify_document, document_id, start_to_close_timeout=DB_TIMEOUT, retry_policy=DB_RETRY
        )
        return status


@workflow.defn
class ExtractPdfTextWorkflow:
    """Temporary processing for the chat's 'process' command: extract the text, split it into chunks and
    embed them in batches, discarding the vectors. Returns the text and saves nothing;
    'save' stores a Document and runs ProcessDocumentWorkflow."""

    @workflow.run
    async def run(self, path: str) -> str:
        text = await workflow.execute_activity(
            extract_pdf_text, path, start_to_close_timeout=EMBED_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        chunk_count = await workflow.execute_activity(
            split_text_preview, path, start_to_close_timeout=DB_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        for start in range(0, chunk_count, BATCH_SIZE):
            await workflow.execute_activity(
                preview_embed_batch,
                args=[path, start, min(start + BATCH_SIZE, chunk_count)],
                start_to_close_timeout=EMBED_TIMEOUT,
                heartbeat_timeout=EMBED_HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        return text
