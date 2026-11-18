from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from steam_discovery.artifacts import ArtifactError
from steam_discovery.insights import VERSION
from .models import DatasetState, Game, GameInsight
from .serializers import GameSerializer, SearchQuerySerializer
from .services import search_index, search_catalog, read_insights
from steam_discovery.filters import FilterError

@api_view(["GET"])
def search(request):
    query = SearchQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    try:
        params = query.validated_data
        payload = search_catalog(params, index=search_index())
    except FilterError as exc:
        return Response({'detail': str(exc)}, status=400)
    except (ArtifactError, RuntimeError) as exc:
        # No external HTTP requests or credentials are involved in serving search.
        return Response({"detail": str(exc)}, status=503)
    return Response(payload)

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
    return Response(read_insights(game))

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
