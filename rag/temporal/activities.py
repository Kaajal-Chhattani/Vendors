import functools
import math
import os

from django.db import close_old_connections, transaction
from temporalio import activity

from chat.service.document_notifications import notify_document_processed
from rag.models import Document, DocumentChunk
from rag.service.cron_management import DocumentProcessor
from rag.service.embedding import get_embedding

FINAL_STATUSES = ('processed', 'error')


def _with_fresh_db_connection(func):
    """Activities run in worker threads that live for days; drop stale DB connections around each call."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()
    return wrapper


@activity.defn
@_with_fresh_db_connection
def claim_document(document_id: int) -> bool:
    """pending -> started. False if the document is not pending (already claimed elsewhere)."""
    return bool(Document.objects.filter(pk=document_id, status='pending').update(status='started'))


@activity.defn
@_with_fresh_db_connection
def prepare_chunks(document_id: int) -> int:
    """Clear chunks left by an earlier crashed run and return how many chunks the text splits into."""
    document = Document.objects.get(pk=document_id)
    document.chunks.all().delete()
    return math.ceil(len(document.raw_text) / DocumentProcessor.chunk_size)


@activity.defn
@_with_fresh_db_connection
def embed_and_save_batch(document_id: int, start: int, end: int) -> int:
    """Embed and save chunks [start, end). Safe to run again: the batch's rows are replaced, not added."""
    document = Document.objects.get(pk=document_id)
    size = DocumentProcessor.chunk_size
    texts = [document.raw_text[i * size:(i + 1) * size] for i in range(start, end)]
    chunks = []
    for offset, text in enumerate(texts):
        activity.heartbeat(start + offset)
        chunks.append(
            DocumentChunk(
                company_id=document.company_id,
                document=document,
                content=text,
                chunk_index=start + offset,
                embedding=get_embedding(text),
            )
        )
    with transaction.atomic():
        DocumentChunk.objects.filter(document=document, chunk_index__gte=start, chunk_index__lt=end).delete()
        DocumentChunk.objects.bulk_create(chunks)
    return len(chunks)


@activity.defn
@_with_fresh_db_connection
def mark_status(document_id: int, status: str) -> None:
    if status not in FINAL_STATUSES:
        raise ValueError(f"status must be one of {FINAL_STATUSES}, got {status!r}")
    Document.objects.filter(pk=document_id).update(status=status)


@activity.defn
@_with_fresh_db_connection
def notify_document(document_id: int) -> None:
    document = Document.objects.filter(pk=document_id).first()
    if document:
        notify_document_processed(document)


@functools.lru_cache(maxsize=8)
def _pdf_text(path: str, mtime: float) -> str:
    if path.lower().endswith(".txt"):  # text fetched from a web link by the chat's 'process <link>'
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def _read_pdf(path: str) -> str:
    """The PDF's text, read once per file per worker (the temporary 'process' steps all use it)."""
    return _pdf_text(path, os.path.getmtime(path))


@activity.defn
def extract_pdf_text(path: str) -> str:
    """Read a PDF's text for the chat's 'process' command. Touches no database rows."""
    return _read_pdf(path)


@activity.defn
def split_text_preview(path: str) -> int:
    """How many chunks the PDF's text splits into. For the chat's 'process' run: counts only, saves nothing."""
    return math.ceil(len(_read_pdf(path)) / DocumentProcessor.chunk_size)


@activity.defn
def preview_embed_batch(path: str, start: int, end: int) -> int:
    """Embed chunks [start, end) of the PDF's text and throw the vectors away. The chat's 'process' run uses it
    to show real embedding progress without saving anything; 'save' does the same work and stores it."""
    text = _read_pdf(path)
    size = DocumentProcessor.chunk_size
    count = 0
    for index in range(start, end):
        activity.heartbeat(index)
        get_embedding(text[index * size:(index + 1) * size])
        count += 1
    return count
