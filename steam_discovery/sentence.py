"""Local MiniLM with no downloads, authentication, or remote code during search."""
import threading
from functools import lru_cache
from pathlib import Path

MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'
MAX_TOKENS = 256
DIMENSIONS = 384

def load_encoder(path):
    from sentence_transformers import SentenceTransformer
    import torch
    torch.set_num_threads(min(4, torch.get_num_threads()))
    model = SentenceTransformer(str(path), device='cpu', local_files_only=True, trust_remote_code=False, token=False)
    model.max_seq_length = MAX_TOKENS
    return model

@lru_cache(maxsize=1)
def cached_encoder(path):
    return load_encoder(Path(path)), threading.Lock()

def encode_query(path, text):
    model, lock = cached_encoder(str(path))
    with lock:
        return model.encode([text], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)[0]

def encode_documents_worker(arguments):
    """Preparation worker; each process caches its own local model."""
    path, texts, batch_size = arguments
    model, _ = cached_encoder(path)
    tokens = model.tokenizer(texts, truncation=False, add_special_tokens=True)['input_ids']
    truncated = sum(len(t) > MAX_TOKENS for t in tokens)
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False, batch_size=batch_size)
    return vectors, truncated
