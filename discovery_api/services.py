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


def search_catalog(params, *, index=None):
    from .models import Game
    from .serializers import GameSerializer
    selected = {key: params.get(key, []) for key in ('required_tag', 'excluded_tag', 'genre')}
    retrieval = (index or search_index()).retrieve(params['q'], params['limit'], params['mode'], selected)
    games = Game.objects.in_bulk([appid for appid, _ in retrieval['matches']])
    results = []
    for rank, (appid, score) in enumerate(retrieval['matches'], 1):
        if appid not in games:
            raise ArtifactError('Catalog and search index differ. Run import_catalog and build_search.')
        results.append({'rank': rank, 'score': score, 'score_type': retrieval['score_type'],
                        'similarity': score if retrieval['score_type'] == 'cosine' else None,
                        **GameSerializer(games[appid]).data})
    return {'query': params['q'], 'mode': params['mode'], 'filters': retrieval['filters'],
            'results': results, 'known_terms': retrieval['known_terms'],
            'unknown_terms': retrieval['unknown_terms'], 'message': retrieval['message']}


def read_insights(game):
    from steam_discovery.insights import VERSION, summarize_points
    from .models import GameInsight
    from .serializers import InsightSerializer
    insight = GameInsight.objects.filter(game=game, analysis_version=VERSION).first()
    status = ('no_reviews' if not game.review_count else 'not_prepared' if not insight else
              'ready' if insight.positive or insight.negative else 'insufficient_evidence')
    return InsightSerializer(dict(
        appid=game.appid, analysis_version=VERSION, status=status,
        collected_review_count=game.review_count,
        analyzed_review_count=insight.analyzed_count if insight else 0,
        positive=summarize_points(insight.positive, 'positive') if insight else [],
        negative=summarize_points(insight.negative, 'negative') if insight else [],
        note='Strengths and drawbacks summarize recurring aspects in the collected English reviews, inferred by local NLP. They are not verified game facts. Conflicting assessments can appear on both sides; recommendation votes and aspect sentiment are separate.',
    )).data
