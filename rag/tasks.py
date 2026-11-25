from celery import shared_task

from chat.service.document_notifications import notify_document_processed
from rag.models import Document
from rag.service.cron_management import DocumentProcessor


def _queue_notifications(docs):
    for doc in docs:
        notify_document_processed_task.delay(doc.pk)


@shared_task
def process_documents_task():
    _queue_notifications(DocumentProcessor().process_pending())


@shared_task
def process_document_task(document_id):
    _queue_notifications(DocumentProcessor().process_by_ids([document_id]))


@shared_task
def process_document_priority_task(document_id):
    _queue_notifications(DocumentProcessor().process_by_ids([document_id]))


@shared_task
def notify_document_processed_task(document_id):
    document = Document.objects.filter(pk=document_id).first()
    if document:
        notify_document_processed(document)
