from rag.models import Document, DocumentChunk
from rag.service.embedding import get_embedding


class DocumentProcessor:
    """Chunks and embeds documents. Callers decide how to announce the result."""
    chunk_size = 1000

    def process_pending(self):
        pending = Document.objects.filter(status='pending')
        return [doc for doc in pending if self._process_one(doc)]

    def process_by_ids(self, document_ids):
        docs = Document.objects.filter(pk__in=document_ids, status='pending')
        return [doc for doc in docs if self._process_one(doc)]

    def _process_one(self, doc):
        """Returns True if this call processed the doc (success or error)."""
        claimed = Document.objects.filter(
            pk=doc.pk, status='pending'
        ).update(status='started')
        if not claimed:
            return False

        try:
            self.create_chunks(doc, doc.raw_text)
            doc.status = 'processed'
            doc.save(update_fields=['status'])
        except Exception as e:
            doc.status = 'error'
            doc.save(update_fields=['status'])
            print(f"Document {doc.pk} failed: {e}")
        return True

    def create_chunks(self, document, text):
        for i in range(0, len(text), self.chunk_size):
            chunk_text = text[i:i + self.chunk_size]
            DocumentChunk.objects.create(
                company=document.company,
                document=document,
                content=chunk_text,
                chunk_index=i // self.chunk_size,
                embedding=get_embedding(chunk_text),
            )
