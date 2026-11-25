from django.core.management.base import BaseCommand

from rag.service.cron_management import DocumentProcessor
from rag.service.kafka_events import get_process_request_consumer, publish_document_processed


class Command(BaseCommand):
    help = "Listen on Kafka for document.process requests, process them, and publish document.processed."

    def handle(self, *args, **options):
        consumer = get_process_request_consumer()
        self.stdout.write(self.style.SUCCESS('Listening for document.process requests...'))
        for record in consumer:
            document_id = record.value.get('document_id')
            if not document_id:
                continue
            self.stdout.write(f"Processing document {document_id}")
            for doc in DocumentProcessor().process_by_ids([document_id]):
                publish_document_processed(doc)
