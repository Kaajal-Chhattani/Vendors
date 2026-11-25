from django.core.management.base import BaseCommand

from chat.service.document_notifications import notify_document_processed
from rag.models import Document
from rag.service.kafka_events import get_consumer


class Command(BaseCommand):
    help = "Listen on Kafka for document.processed events and post a chat message about them."

    def handle(self, *args, **options):
        consumer = get_consumer()
        self.stdout.write(self.style.SUCCESS('Listening for document.processed events...'))
        for record in consumer:
            document = Document.objects.filter(pk=record.value.get('document_id')).first()
            if document is None:
                continue
            conversation = notify_document_processed(document)
            if conversation:
                self.stdout.write(f"Posted update for document {document.pk} to conversation {conversation.pk}")
