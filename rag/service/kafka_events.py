import json

from django.conf import settings


def _get_producer():
    from kafka import KafkaProducer

    return KafkaProducer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda value: json.dumps(value).encode('utf-8'),
    )


_producer = None


def _send(topic, message):
    global _producer
    if _producer is None:
        _producer = _get_producer()
    _producer.send(topic, value=message)
    _producer.flush()


def publish_process_request(document):
    """Ask the Kafka document worker to process this document."""
    _send(settings.KAFKA_DOCUMENT_PROCESS_TOPIC, {'document_id': document.pk})


def publish_document_processed(document):
    """Announce on Kafka that a document finished processing (or failed)."""
    _send(settings.KAFKA_DOCUMENT_PROCESSED_TOPIC, {
        'document_id': document.pk,
        'company_id': document.company_id,
        'user_id': document.created_by_id,
        'status': document.status,
    })


def _get_consumer(topic, group_id, auto_offset_reset):
    from kafka import KafkaConsumer

    return KafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=group_id,
        value_deserializer=lambda value: json.loads(value.decode('utf-8')),
        auto_offset_reset=auto_offset_reset,
    )


def get_consumer():
    return _get_consumer(settings.KAFKA_DOCUMENT_PROCESSED_TOPIC, 'chat-notifications', 'latest')


def get_process_request_consumer():
    # 'earliest' so requests sent while the worker was down still get processed.
    return _get_consumer(settings.KAFKA_DOCUMENT_PROCESS_TOPIC, 'document-processors', 'earliest')
