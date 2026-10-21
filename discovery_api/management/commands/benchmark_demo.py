import json
import os
import statistics
import time
from pathlib import Path
from unittest.mock import patch
import psutil
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from discovery_api.models import Game, Review, GameInsight
from steam_discovery.insights import VERSION
from discovery_api.services import _load_index

class Command(BaseCommand):
    help = "Measure cold/warm HTTP handler latency, memory, artifact size, and offline readiness."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="validation/benchmark.json")

    def handle(self, *args, **options):
        client = Client()
        query = "Explore an open world and build a base to survive with friends"
        timings = []
        _load_index.cache_clear()
        # Explicitly forbid network connections and clear the key during measurement.
        with patch.dict(os.environ, {"STEAM_API_KEY": ""}), patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
            start = time.perf_counter()
            response = client.get("/api/v1/search/", {"q": query})
            cold = time.perf_counter() - start
            if response.status_code != 200:
                raise CommandError(str(response.json()))
            for _ in range(20):
                start = time.perf_counter()
                response = client.get("/api/v1/search/", {"q": query})
                timings.append(time.perf_counter() - start)
            appid = response.json()["results"][0]["appid"]
            if client.get(f"/api/v1/games/{appid}/").status_code != 200 or client.get(f"/api/v1/games/{appid}/insights/").status_code != 200:
                raise CommandError("Game details or insights unavailable")
        bundle = settings.DISCOVERY_ARTIFACTS / (settings.DISCOVERY_ARTIFACTS / "current").read_text().strip()
        report = {"games": Game.objects.count(), "reviews": Review.objects.count(), "prepared_games": GameInsight.objects.filter(analysis_version=VERSION).count(), "cold_search_seconds": round(cold, 4), "warm_search_median_seconds": round(statistics.median(timings), 4), "warm_search_max_seconds": round(max(timings), 4), "warm_search_target_met": max(timings) < 2, "backend_rss_mb": round(psutil.Process().memory_info().rss / 1024**2, 1), "artifact_size_mb": round(sum(p.stat().st_size for p in bundle.iterdir()) / 1024**2, 1), "offline_without_key": True, "query": query, "top_results": [{"appid": r["appid"], "name": r["name"]} for r in response.json()["results"]]}
        path = Path(options["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report, indent=2))
