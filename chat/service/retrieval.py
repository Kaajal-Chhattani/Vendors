from rag.models import DocumentChunk
from rag.service.embedding import get_embedding, cosine_similarity

RELEVANCE_THRESHOLD = 0.35


def find_relevant_chunks(text, company, limit=3):
    query_embedding = get_embedding(text)
    chunks = DocumentChunk.objects.filter(company=company).exclude(embedding__isnull=True)
    scored = [(c, cosine_similarity(query_embedding, c.embedding)) for c in chunks]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, score in scored[:limit] if score >= RELEVANCE_THRESHOLD]
