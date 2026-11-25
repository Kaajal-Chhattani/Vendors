import asyncio
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.management.base import BaseCommand
from temporalio.client import Client
from temporalio.worker import Worker

from rag.temporal.activities import (
    claim_document,
    embed_and_save_batch,
    extract_pdf_text,
    preview_embed_batch,
    split_text_preview,
    mark_status,
    notify_document,
    prepare_chunks,
)
from rag.temporal.workflows import ExtractPdfTextWorkflow, ProcessDocumentWorkflow

# Embedding is CPU-heavy, so keep this low; it is also the number of activities that run at once.
MAX_CONCURRENT_ACTIVITIES = 2


class Command(BaseCommand):
    help = "Run the Temporal worker that processes documents (workflow + activities)."

    def handle(self, *args, **options):
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.stdout.write('Temporal worker stopped.')

    async def _run(self):
        client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
        # The activities are plain functions that use the Django ORM, so they run in threads.
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_ACTIVITIES) as executor:
            worker = Worker(
                client,
                task_queue=settings.TEMPORAL_DOCUMENTS_TASK_QUEUE,
                workflows=[ProcessDocumentWorkflow, ExtractPdfTextWorkflow],
                activities=[claim_document, prepare_chunks, embed_and_save_batch, mark_status, notify_document, extract_pdf_text, split_text_preview, preview_embed_batch],
                activity_executor=executor,
                max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
            )
            self.stdout.write(self.style.SUCCESS(
                f'Temporal worker listening on queue "{settings.TEMPORAL_DOCUMENTS_TASK_QUEUE}" at {settings.TEMPORAL_ADDRESS}'
            ))
            await worker.run()
