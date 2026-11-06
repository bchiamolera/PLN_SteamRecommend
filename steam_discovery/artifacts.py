import hashlib
import json
import os
import shutil
import uuid
import threading
from pathlib import Path
import numpy as np
from .preprocessing import VERSION
from .search import TRAINING, normalize_rows, query_vector, rank

SCHEMA_VERSION = 1

class ArtifactError(RuntimeError):
    pass

def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def save_bundle(root, model, vectors, appids, dataset_fingerprint, *, enrich=None, reuse=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    directory = root / name
    directory.mkdir()
    try:
        if reuse is None:
            model.wv.save(str(directory / "word2vec.kv"))
            np.save(directory / "vectors.npy", normalize_rows(vectors))
            np.save(directory / "appids.npy", np.asarray(appids, dtype=np.int64))
        else:
            for filename in reuse.manifest['files']:
                if filename.startswith('word2vec.kv') or filename in {'vectors.npy', 'appids.npy'}:
                    shutil.copy2(reuse.directory / filename, directory / filename)
        extra = enrich(directory) if enrich else {}
        manifest = {
            "schema_version": 2 if enrich else SCHEMA_VERSION, "preprocessing_version": VERSION,
            "dataset_fingerprint": dataset_fingerprint, "training": TRAINING,
            "ordered_appids": [int(a) for a in appids],
            **extra,
            "files": {p.relative_to(directory).as_posix(): fingerprint(p) for p in directory.rglob('*') if p.is_file()},
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pointer = root / f"current-{name}.tmp"
        pointer.write_text(name, encoding="ascii")
        os.replace(pointer, root / "current")
    except Exception:
        # Keep interrupted v2 preparation for inspection and checkpoint recovery.
        # Only remove a newly created legacy bundle after verifying its boundary.
        if not enrich and directory.exists() and directory.resolve().parent == root.resolve():
            shutil.rmtree(directory)
        raise
    return directory

class SearchIndex:
    def __init__(self, root, expected_fingerprint):
        from gensim.models import KeyedVectors
        from .preprocessing import english_stopwords
        english_stopwords()
        try:
            root = Path(root)
            name = (root / "current").read_text(encoding="ascii").strip()
            if len(name) != 32 or any(c not in "0123456789abcdef" for c in name):
                raise ValueError("Invalid bundle pointer")
            directory = self.directory = root / name
            self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            m = self.manifest
            if (m["schema_version"] not in {1, 2} or m["preprocessing_version"] != VERSION
                    or m["training"] != TRAINING or m["dataset_fingerprint"] != expected_fingerprint):
                raise ValueError("Incompatible dataset or model version")
            for filename, digest in m["files"].items():
                path = (directory / filename).resolve()
                if not path.is_relative_to(directory.resolve()) or fingerprint(path) != digest:
                    raise ValueError("Artifact checksum mismatch")
            required = {'word2vec.kv', 'vectors.npy', 'appids.npy'}
            if m['schema_version'] == 2:
                required |= {'bm25.npz', 'vocabulary.json', 'metadata.json', 'sentence_vectors.npy'}
                from .lexical import PARAMETERS
                from .sentence import MODEL_ID, MAX_TOKENS
                if m['bm25'] != PARAMETERS or m['sentence']['model_id'] != MODEL_ID or m['sentence']['max_tokens'] != MAX_TOKENS:
                    raise ValueError('Incompatible retrieval configuration')
            if not required.issubset(m['files']): raise ValueError('Missing artifact checksums')
            self.appids = np.load(directory / "appids.npy", allow_pickle=False)
            self.vectors = np.load(directory / "vectors.npy", mmap_mode="r", allow_pickle=False)
            self.keyed_vectors = KeyedVectors.load(str(directory / "word2vec.kv"), mmap="r")
            if (self.appids.tolist() != m["ordered_appids"] or len(set(self.appids)) != len(self.appids)
                    or self.vectors.shape != (len(self.appids), TRAINING["vector_size"])
                    or not np.isfinite(self.vectors).all()):
                raise ValueError("Invalid row alignment or vectors")
            self._metadata = self._lexical = self._sentence_vectors = None
            self._lock = threading.RLock()
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            self.close()
            raise ArtifactError("Search artifacts unavailable or incompatible. Run import_catalog, then build_search.") from exc

    def close(self):
        for array in [getattr(self, "vectors", None), getattr(self, '_sentence_vectors', None), getattr(getattr(self, "keyed_vectors", None), "vectors", None)]:
            if isinstance(array, np.memmap):
                array._mmap.close()

    def search(self, text, limit):
        vector, known, unknown = query_vector(text, self.keyed_vectors)
        if vector is None or not np.any(vector):
            return [], known, unknown
        positions, scores = rank(vector, self.vectors, limit, normalized=True)
        return [(int(self.appids[i]), float(s)) for i, s in zip(positions, scores)], known, unknown

    def require_upgrade(self):
        if self.manifest['schema_version'] < 2:
            raise ArtifactError('This method/filters need updated artifacts. Run: python manage.py build_search --reuse-word2vec')

    @property
    def metadata(self):
        self.require_upgrade()
        with self._lock:
            if self._metadata is None:
                from .filters import MetadataIndex
                records = json.loads((self.directory / 'metadata.json').read_text(encoding='utf-8'))
                if [r['appid'] for r in records] != self.appids.tolist(): raise ArtifactError('Metadata row alignment differs. Rebuild search.')
                self._metadata = MetadataIndex(records)
        return self._metadata

    def retrieve(self, text, limit, mode='word2vec', filters=None):
        from .retrieval import MODES, CANDIDATES, top_rows, reciprocal_rank_fusion
        if mode not in MODES: raise ValueError('Unknown search method')
        filters = filters or {}
        selected = any(filters.values())
        normalized = {field: [] for field in ('required_tag', 'excluded_tag', 'genre')}
        mask = np.ones(len(self.appids), dtype=bool)
        if selected: mask, normalized = self.metadata.eligible(**filters)
        known, unknown, rankings, raw_scores = [], [], [], None
        if mode != 'word2vec': self.require_upgrade()
        if mode in {'word2vec', 'hybrid_word2vec'}:
            vector, known, unknown = query_vector(text, self.keyed_vectors)
            if vector is None or not np.any(vector):
                raw_scores = np.full(len(mask), -np.inf)
            else:
                raw_scores = self.vectors @ (vector / np.linalg.norm(vector))
            valid = mask & np.any(self.vectors != 0, axis=1)
            # Preserve original stable notebook tie order for the baseline.
            if mode == 'word2vec':
                rows = np.flatnonzero(valid & np.isfinite(raw_scores))
                rows = rows[np.argsort(-raw_scores[rows], kind='stable')[:limit]]
            else:
                rows = top_rows(raw_scores, self.appids, valid, CANDIDATES)
            rankings.append(rows)
        if mode in {'sentence', 'hybrid_sentence'}:
            from .sentence import encode_query, DIMENSIONS
            with self._lock:
                if self._sentence_vectors is None:
                    vectors = np.load(self.directory / 'sentence_vectors.npy', mmap_mode='r', allow_pickle=False)
                    if vectors.shape != (len(mask), DIMENSIONS) or not np.isfinite(vectors).all():
                        vectors._mmap.close()
                        raise ArtifactError('Invalid sentence vectors. Rebuild search.')
                    self._sentence_vectors = vectors
            try:
                vector = encode_query(self.directory / 'sentence_model', text)
            except (OSError, ImportError, ValueError) as exc:
                raise ArtifactError('Sentence model unavailable locally. Rebuild search after prepare_sentence_model.') from exc
            raw_scores = self._sentence_vectors @ vector
            valid = mask & np.any(self._sentence_vectors != 0, axis=1)
            rankings.append(top_rows(raw_scores, self.appids, valid, CANDIDATES if mode.startswith('hybrid') else limit))
        if mode in {'bm25', 'hybrid_word2vec', 'hybrid_sentence'}:
            with self._lock:
                if self._lexical is None:
                    from .lexical import BM25Index
                    try:
                        self._lexical = BM25Index.load(self.directory)
                    except (OSError, ValueError, KeyError) as exc:
                        raise ArtifactError('Invalid BM25 artifacts. Rebuild search.') from exc
                    if self._lexical.matrix.shape[0] != len(mask): raise ArtifactError('BM25 row alignment differs. Rebuild search.')
            lexical_scores = self._lexical.scores(text)
            rankings.append(top_rows(lexical_scores, self.appids, mask, CANDIDATES if mode.startswith('hybrid') else limit, positive_only=True))
            if mode == 'bm25': raw_scores = lexical_scores
        if mode.startswith('hybrid'):
            ranked = reciprocal_rank_fusion(rankings, self.appids, limit)
            score_type = 'rrf'
        else:
            ranked = [(int(p), float(raw_scores[p])) for p in rankings[0]]
            score_type = 'bm25' if mode == 'bm25' else 'cosine'
        message = ''
        if not ranked:
            message = 'No games match this query and the selected filters. Try broader English terms or fewer filters.'
        elif mode == 'hybrid_word2vec' and not known:
            message = 'Word2Vec found no known terms; results come from BM25.'
        return {'matches': [(int(self.appids[p]), float(s)) for p, s in ranked], 'score_type': score_type, 'known_terms': known, 'unknown_terms': unknown, 'filters': normalized, 'message': message}
