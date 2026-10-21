"""Deterministic Word2Vec training and cosine ranking, without Django dependencies."""
import numpy as np
from .preprocessing import preprocess

TRAINING = dict(vector_size=190, window=5, min_count=1, sg=1, seed=42, workers=1, epochs=10)

def train_word2vec(sentences):
    from gensim.models import Word2Vec
    return Word2Vec(sentences=sentences, **TRAINING)

def document_vector(tokens, keyed_vectors):
    vectors = [keyed_vectors[t] for t in tokens if t in keyed_vectors]
    return np.mean(vectors, axis=0) if vectors else np.zeros(keyed_vectors.vector_size, dtype=np.float32)

def query_vector(text, keyed_vectors):
    tokens = preprocess(text)
    known = [t for t in tokens if t in keyed_vectors]
    unknown = [t for t in tokens if t not in keyed_vectors]
    return (document_vector(known, keyed_vectors) if known else None), known, unknown

def normalize_rows(matrix):
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)

def rank(vector, matrix, k=10, *, normalized=False):
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    if not np.isfinite(vector).all() or not np.any(vector):
        raise ValueError("The query has no valid search vector")
    matrix = matrix if normalized else normalize_rows(matrix)
    scores = matrix @ (vector / np.linalg.norm(vector))
    valid = np.flatnonzero(np.any(matrix != 0, axis=1))
    indices = valid[np.argsort(-scores[valid], kind="stable")[:k]]
    return indices, scores[indices]
