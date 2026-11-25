import math
from sentence_transformers import SentenceTransformer
_model=SentenceTransformer('all-MiniLM-L6-v2')


def get_embedding(text):
    return _model.encode(text).tolist()


def cosine_similarity(vec1, vec2):
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)