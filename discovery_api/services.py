from functools import lru_cache
from django.conf import settings
from steam_discovery.artifacts import ArtifactError, SearchIndex
from .models import DatasetState

@lru_cache(maxsize=1)
def _load_index(root, bundle, dataset_fingerprint):
    return SearchIndex(root, dataset_fingerprint)

def search_index():
    state = DatasetState.objects.filter(key="catalog").first()
    if not state:
        raise ArtifactError("Catalog missing. Run import_catalog, then build_search.")
    try:
        bundle = (settings.DISCOVERY_ARTIFACTS / "current").read_text(encoding="ascii").strip()
    except OSError:
        raise ArtifactError("Search artifacts missing. Run build_search.") from None
    return _load_index(str(settings.DISCOVERY_ARTIFACTS), bundle, state.fingerprint)
