from django.core.management.base import BaseCommand

from chat.service.document_notifications import notify_document_processed
from rag.service.cron_management import DocumentProcessor


class Command(BaseCommand):
    help = "Embed pending documents and update their status"

    def handle(self, *args, **options):
        for doc in DocumentProcessor().process_pending():
            notify_document_processed(doc)
