"""Sparse BM25: prepare document weights offline and query term columns."""
import json
from collections import Counter
import numpy as np
from scipy import sparse
from .preprocessing import preprocess

PARAMETERS = {"k1": 1.5, "b": 0.75, "fields": ["name", "genres", "user_tags", "description"], "version": 1}

class BM25Index:
    def __init__(self, matrix, vocabulary):
        self.matrix = matrix.tocsc()
        self.vocabulary = vocabulary

    @classmethod
    def build(cls, documents):
        vocabulary, rows, columns, frequencies, lengths = {}, [], [], [], []
        for row, text in enumerate(documents):
            tokens = preprocess(text)
            lengths.append(len(tokens))
            for term, count in Counter(tokens).items():
                column = vocabulary.setdefault(term, len(vocabulary))
                rows.append(row); columns.append(column); frequencies.append(count)
        shape = (len(lengths), len(vocabulary))
        tf = sparse.csr_matrix((np.asarray(frequencies, dtype=np.float32), (rows, columns)), shape=shape)
        lengths = np.asarray(lengths, dtype=np.float32)
        df = np.asarray((tf > 0).sum(axis=0)).ravel()
        idf = np.log1p((len(lengths) - df + 0.5) / (df + 0.5))
        coo = tf.tocoo()
        average = max(float(lengths.mean()), 1.0) if len(lengths) else 1.0
        norm = PARAMETERS['k1'] * (1 - PARAMETERS['b'] + PARAMETERS['b'] * lengths / average)
        weights = idf[coo.col] * coo.data * (PARAMETERS['k1'] + 1) / (coo.data + norm[coo.row])
        return cls(sparse.csc_matrix((weights.astype(np.float32), (coo.row, coo.col)), shape=shape), vocabulary)

    def scores(self, query):
        columns = [self.vocabulary[t] for t in set(preprocess(query)) if t in self.vocabulary]
        return np.asarray(self.matrix[:, columns].sum(axis=1)).ravel() if columns else np.zeros(self.matrix.shape[0], dtype=np.float32)

    def save(self, directory):
        sparse.save_npz(directory / 'bm25.npz', self.matrix)
        (directory / 'vocabulary.json').write_text(json.dumps(self.vocabulary), encoding='utf-8')

    @classmethod
    def load(cls, directory):
        matrix = sparse.load_npz(directory / 'bm25.npz')
        vocabulary = json.loads((directory / 'vocabulary.json').read_text(encoding='utf-8'))
        if matrix.shape[1] != len(vocabulary) or sorted(vocabulary.values()) != list(range(len(vocabulary))) or not np.isfinite(matrix.data).all():
            raise ValueError('Invalid BM25 index')
        return cls(matrix, vocabulary)
