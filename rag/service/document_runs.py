"""Start / stop a document's Temporal run. Shared by the Document admin and the chat."""
import logging

from rag.models import Document
from rag.temporal.client import start_document_processing, stop_document_processing

logger = logging.getLogger(__name__)

TEMPORAL_VIA = ('temporal', 'temporal_extract')


def can_stop(document):
    return document.status == 'started' and document.processed_via == 'temporal'


def can_start(document):
    """Stopped, failed, waiting, or only text-extracted by chat 'process'. A finished full Temporal run needs no start.
    A waiting or failed document with no method yet (its first start could not reach the method) can also be started."""
    if not document.processed_via:
        return document.status in ('pending', 'error')
    if document.processed_via not in TEMPORAL_VIA:
        return False
    if document.status == 'processed':
        return document.processed_via == 'temporal_extract'
    return document.status in ('pending', 'error')


def stop_document(document):
    """Cancel the Temporal run and set the document back to pending. Returns (ok, message)."""
    if not can_stop(document):
        return False, f'Document #{document.pk} has no running Temporal run to stop.'
    try:
        stop_document_processing(document.pk)
    except Exception:
        logger.exception('Could not stop the Temporal workflow for document %s', document.pk)
        return False, f'Could not reach Temporal to stop document #{document.pk}.'
    Document.objects.filter(pk=document.pk, status='started').update(status='pending')
    return True, f'Document #{document.pk} stopped and set back to pending.'


def start_document(document):
    """(Re)start the full Temporal workflow. Returns (ok, message)."""
    if not can_start(document):
        return False, f'Document #{document.pk} cannot be started with Temporal.'
    previous_status, previous_via = document.status, document.processed_via
    Document.objects.filter(pk=document.pk).update(status='pending', processed_via='temporal')
    try:
        started = start_document_processing(document.pk)
    except Exception:
        logger.exception('Could not start the Temporal workflow for document %s', document.pk)
        Document.objects.filter(pk=document.pk).update(status=previous_status, processed_via=previous_via)
        return False, f'Could not reach Temporal for document #{document.pk}. Is the server running?'
    if not started:
        Document.objects.filter(pk=document.pk).update(status=previous_status, processed_via=previous_via)
        return False, f'Document #{document.pk} still has a run in progress (a stop may not have finished). Try again shortly.'
    return True, f'Document #{document.pk} started on Temporal.'
