"""Deterministic ranking and rank fusion without mixing score scales."""
import numpy as np

MODES = ('word2vec', 'bm25', 'sentence', 'hybrid_word2vec', 'hybrid_sentence')
RRF_K = 60
CANDIDATES = 200

def top_rows(scores, appids, mask, limit, positive_only=False):
    valid = mask & np.isfinite(scores)
    if positive_only: valid &= scores > 0
    rows = np.flatnonzero(valid)
    return rows[np.lexsort((appids[rows], -scores[rows]))[:limit]]

def reciprocal_rank_fusion(rankings, appids, limit):
    scores = {}
    for ranking in rankings:
        for rank, position in enumerate(ranking, 1):
            scores[int(position)] = scores.get(int(position), 0.0) + 1.0 / (RRF_K + rank)
    rows = sorted(scores, key=lambda p: (-scores[p], int(appids[p])))[:limit]
    return [(p, scores[p]) for p in rows]
