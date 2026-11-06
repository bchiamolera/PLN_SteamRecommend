from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from steam_discovery.artifacts import ArtifactError
from steam_discovery.insights import VERSION, summarize_points
from .models import DatasetState, Game, GameInsight
from .serializers import GameSerializer, InsightSerializer, SearchQuerySerializer
from .services import search_index
from steam_discovery.filters import FilterError

@api_view(["GET"])
def search(request):
    query = SearchQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        params = query.validated_data
        selected = {key: params[key] for key in ('required_tag', 'excluded_tag', 'genre')}
        retrieval = search_index().retrieve(params['q'], params['limit'], params['mode'], selected)
        matches = retrieval['matches']
    except FilterError as exc:
        return Response({'detail': str(exc)}, status=400)
    except (ArtifactError, RuntimeError) as exc:
        # No external HTTP requests or credentials are involved in serving search.
        return Response({"detail": str(exc)}, status=503)
    games = Game.objects.in_bulk([appid for appid, _ in matches])
    results = []
    for rank, (appid, score) in enumerate(matches, 1):
        if appid not in games:
            return Response({"detail": "Catalog and search index differ. Run import_catalog and build_search."}, status=503)
        results.append({'rank': rank, 'score': score, 'score_type': retrieval['score_type'], 'similarity': score if retrieval['score_type'] == 'cosine' else None, **GameSerializer(games[appid]).data})
    return Response({'query': params['q'], 'mode': params['mode'], 'filters': retrieval['filters'], 'results': results, 'known_terms': retrieval['known_terms'], 'unknown_terms': retrieval['unknown_terms'], 'message': retrieval['message']})

@api_view(['GET'])
def filters(request):
    try:
        index = search_index()
        return Response(index.metadata.facets())
    except (ArtifactError, RuntimeError) as exc:
        return Response({'detail': str(exc)}, status=503)

@api_view(["GET"])
def game_detail(request, appid):
    return Response(GameSerializer(get_object_or_404(Game, pk=appid)).data)

@api_view(["GET"])
def game_insights(request, appid):
    game = get_object_or_404(Game, pk=appid)
    insight = GameInsight.objects.filter(game=game, analysis_version=VERSION).first()
    status = "no_reviews" if not game.review_count else "not_prepared" if not insight else "ready" if insight.positive or insight.negative else "insufficient_evidence"
    payload = dict(
        appid=appid, analysis_version=VERSION, status=status,
        collected_review_count=game.review_count,
        analyzed_review_count=insight.analyzed_count if insight else 0,
        positive=summarize_points(insight.positive, "positive") if insight else [],
        negative=summarize_points(insight.negative, "negative") if insight else [],
        note="Strengths and drawbacks summarize recurring aspects in the collected English reviews, inferred by local NLP. They are not verified game facts. Conflicting assessments can appear on both sides; recommendation votes and aspect sentiment are separate.",
    )
    return Response(InsightSerializer(payload).data)

@api_view(["GET"])
def health(request):
    try:
        catalog = DatasetState.objects.filter(key="catalog").exists()
        reviews = DatasetState.objects.filter(key="reviews").exists()
        prepared = GameInsight.objects.filter(analysis_version=VERSION).count()
        try:
            search_index()
            ready, message = True, ""
        except (ArtifactError, RuntimeError) as exc:
            ready, message = False, str(exc)
        return Response({"database": "ready", "catalog": catalog, "reviews": reviews, "search": "ready" if ready else "unavailable", "insights_prepared_games": prepared, "detail": message}, status=200 if catalog and ready else 503)
    except DatabaseError:
        return Response({"database": "unavailable", "detail": "Run python manage.py migrate."}, status=503)
