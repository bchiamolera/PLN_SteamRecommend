"""Exact metadata filters; a missing tag does not prove a theme is absent."""
import unicodedata
import numpy as np

def canonical(value):
    return unicodedata.normalize('NFKC', value).strip().casefold()

class FilterError(ValueError):
    pass

class MetadataIndex:
    def __init__(self, records):
        self.records = records
        self.labels = {'tags': {}, 'genres': {}}
        self.postings = {'tags': {}, 'genres': {}}
        for position, record in enumerate(records):
            for kind, field in [('tags', 'user_tags'), ('genres', 'genres')]:
                for label in record[field]:
                    key = canonical(label)
                    if not key: continue
                    self.labels[kind].setdefault(key, label.strip())
                    self.postings[kind].setdefault(key, set()).add(position)

    def facets(self):
        return {kind: [{'label': self.labels[kind][key], 'count': len(rows)} for key, rows in sorted(postings.items())] for kind, postings in self.postings.items()}

    def eligible(self, required_tag=(), excluded_tag=(), genre=()):
        normalized = {}
        for field, values, kind in [('required_tag', required_tag, 'tags'), ('excluded_tag', excluded_tag, 'tags'), ('genre', genre, 'genres')]:
            keys = sorted({canonical(v) for v in values})
            unknown = [k for k in keys if k not in self.labels[kind]]
            if unknown: raise FilterError(f"Unknown {field}: {', '.join(unknown)}")
            normalized[field] = [self.labels[kind][k] for k in keys]
        if set(map(canonical, normalized['required_tag'])) & set(map(canonical, normalized['excluded_tag'])):
            raise FilterError('A tag cannot be required and excluded at the same time.')
        mask = np.ones(len(self.records), dtype=bool)
        for label in normalized['required_tag']:
            match = np.zeros(len(mask), dtype=bool)
            match[list(self.postings['tags'][canonical(label)])] = True
            mask &= match
        if normalized['genre']:
            match = np.zeros(len(mask), dtype=bool)
            for label in normalized['genre']: match[list(self.postings['genres'][canonical(label)])] = True
            mask &= match
        for label in normalized['excluded_tag']:
            mask[list(self.postings['tags'][canonical(label)])] = False
        return mask, normalized
