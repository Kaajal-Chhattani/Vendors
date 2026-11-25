import uuid
from datetime import timedelta

from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

WORKFLOW_NAME = 'ProcessDocumentWorkflow'


async def _start(document_id):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    try:
        await client.start_workflow(
            WORKFLOW_NAME,
            document_id,
            id=f'document-{document_id}',
            task_queue=settings.TEMPORAL_DOCUMENTS_TASK_QUEUE,
        )
    except WorkflowAlreadyStartedError:
        return False
    return True


def start_document_processing(document_id):
    """Start the workflow for a document. False if a run for it is already in progress."""
    return async_to_sync(_start)(document_id)


async def _stop(document_id):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    try:
        await client.get_workflow_handle(f'document-{document_id}').cancel()
    except RPCError as error:
        if error.status in (RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION):
            return False  # no run, or it already closed
        raise
    return True


def stop_document_processing(document_id):
    """Cancel the document's running workflow. False if there is no run in progress."""
    return async_to_sync(_stop)(document_id)


async def _extract(path):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    workflow_id = f'pdf-extract-{uuid.uuid4().hex}'
    text = await client.execute_workflow(
        'ExtractPdfTextWorkflow',
        path,
        id=workflow_id,
        task_queue=settings.TEMPORAL_DOCUMENTS_TASK_QUEUE,
        execution_timeout=timedelta(minutes=2),
    )
    return text, workflow_id


def extract_pdf_text(path):
    """Run the temporary 'process' workflow and wait for it. Returns (text, workflow_id); no Document is created."""
    return async_to_sync(_extract)(path)


async def _start_extract(path):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    workflow_id = f'pdf-extract-{uuid.uuid4().hex}'
    await client.start_workflow(
        'ExtractPdfTextWorkflow',
        path,
        id=workflow_id,
        task_queue=settings.TEMPORAL_DOCUMENTS_TASK_QUEUE,
        execution_timeout=timedelta(minutes=10),
    )
    return workflow_id


def start_pdf_extract(path):
    """Start the temporary 'process' workflow without waiting for it. Returns its workflow id; no Document is created."""
    return async_to_sync(_start_extract)(path)


async def _extract_text(workflow_id):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    return await client.get_workflow_handle(workflow_id).result()


def get_extract_text(workflow_id):
    """The text a finished 'process' workflow returned. Raises if it failed or was cancelled."""
    return async_to_sync(_extract_text)(workflow_id)


async def _stop_extract(workflow_id):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    try:
        await client.get_workflow_handle(workflow_id).cancel()
    except RPCError as error:
        if error.status in (RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION):
            return False
        raise
    return True


def stop_pdf_extract(workflow_id):
    """Cancel a running 'process' workflow. False if it is not running."""
    return async_to_sync(_stop_extract)(workflow_id)
