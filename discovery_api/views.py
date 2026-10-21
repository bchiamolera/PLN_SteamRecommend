from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from steam_discovery.artifacts import ArtifactError
from steam_discovery.insights import VERSION
from .models import DatasetState, Game, GameInsight
from .serializers import GameSerializer, InsightSerializer, SearchQuerySerializer
from .services import search_index

@api_view(["GET"])
def search(request):
    query = SearchQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        matches, known, unknown = search_index().search(query.validated_data["q"], query.validated_data["limit"])
    except (ArtifactError, RuntimeError) as exc:
        # No external HTTP requests or credentials are involved in serving search.
        return Response({"detail": str(exc)}, status=503)
    games = Game.objects.in_bulk([appid for appid, _ in matches])
    results = []
    for rank, (appid, score) in enumerate(matches, 1):
        if appid not in games:
            return Response({"detail": "Catalog and search index differ. Run import_catalog and build_search."}, status=503)
        results.append({"rank": rank, "similarity": score, **GameSerializer(games[appid]).data})
    return Response({"query": query.validated_data["q"], "results": results, "known_terms": known, "unknown_terms": unknown, "message": "" if matches else "No searchable words found. Try different English words."})

@api_view(["GET"])
def game_detail(request, appid):
    return Response(GameSerializer(get_object_or_404(Game, pk=appid)).data)

@api_view(["GET"])
def game_insights(request, appid):
    game = get_object_or_404(Game, pk=appid)
    insight = GameInsight.objects.filter(game=game, analysis_version=VERSION).first()
    status = "no_reviews" if not game.review_count else "not_prepared" if not insight else "ready" if insight.positive or insight.negative else "insufficient_evidence"
    payload = dict(appid=appid, analysis_version=VERSION, status=status, collected_review_count=game.review_count, analyzed_review_count=insight.analyzed_count if insight else 0, positive=insight.positive if insight else [], negative=insight.negative if insight else [], note="Recurring observations in the collected English reviews, inferred by local NLP. Supporting counts are not Steam-wide statistics; recommendation votes and aspect sentiment are separate.")
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
