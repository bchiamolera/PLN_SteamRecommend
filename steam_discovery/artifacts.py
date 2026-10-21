import hashlib
import json
import os
import shutil
import uuid
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

def save_bundle(root, model, vectors, appids, dataset_fingerprint):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    name = uuid.uuid4().hex
    directory = root / name
    directory.mkdir()
    try:
        model.wv.save(str(directory / "word2vec.kv"))
        np.save(directory / "vectors.npy", normalize_rows(vectors))
        np.save(directory / "appids.npy", np.asarray(appids, dtype=np.int64))
        manifest = {
            "schema_version": SCHEMA_VERSION, "preprocessing_version": VERSION,
            "dataset_fingerprint": dataset_fingerprint, "training": TRAINING,
            "ordered_appids": [int(a) for a in appids],
            "files": {p.name: fingerprint(p) for p in directory.iterdir()},
        }
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        pointer = root / f"current-{name}.tmp"
        pointer.write_text(name, encoding="ascii")
        os.replace(pointer, root / "current")
    except Exception:
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
            directory = root / name
            self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            m = self.manifest
            if (m["schema_version"] != SCHEMA_VERSION or m["preprocessing_version"] != VERSION
                    or m["training"] != TRAINING or m["dataset_fingerprint"] != expected_fingerprint):
                raise ValueError("Incompatible dataset or model version")
            for filename, digest in m["files"].items():
                if Path(filename).name != filename or fingerprint(directory / filename) != digest:
                    raise ValueError("Artifact checksum mismatch")
            self.appids = np.load(directory / "appids.npy", allow_pickle=False)
            self.vectors = np.load(directory / "vectors.npy", mmap_mode="r", allow_pickle=False)
            self.keyed_vectors = KeyedVectors.load(str(directory / "word2vec.kv"), mmap="r")
            if (self.appids.tolist() != m["ordered_appids"] or len(set(self.appids)) != len(self.appids)
                    or self.vectors.shape != (len(self.appids), TRAINING["vector_size"])
                    or not np.isfinite(self.vectors).all()):
                raise ValueError("Invalid row alignment or vectors")
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            self.close()
            raise ArtifactError("Search artifacts unavailable or incompatible. Run import_catalog, then build_search.") from exc

    def close(self):
        for array in [getattr(self, "vectors", None), getattr(getattr(self, "keyed_vectors", None), "vectors", None)]:
            if isinstance(array, np.memmap):
                array._mmap.close()

    def search(self, text, limit):
        vector, known, unknown = query_vector(text, self.keyed_vectors)
        if vector is None or not np.any(vector):
            return [], known, unknown
        positions, scores = rank(vector, self.vectors, limit, normalized=True)
        return [(int(self.appids[i]), float(s)) for i, s in zip(positions, scores)], known, unknown
