import time
from collections import defaultdict
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from discovery_api.models import DatasetState, Game, GameInsight, Review
from steam_discovery.insights import AspectAnalyzer, VERSION, aggregate

class Command(BaseCommand):
    help = "Prepare local, evidence-backed insights. Resume safely with --resume."

    def add_arguments(self, parser):
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--appid", type=int, action="append", help="Restrict preparation to selected games; repeatable.")

    def handle(self, *args, **options):
        if not DatasetState.objects.filter(key="reviews").exists():
            raise CommandError("Run import_reviews first.")
        try:
            analyzer = AspectAnalyzer()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from None
        games = Game.objects.filter(review_count__gt=0).order_by("appid")
        if options["appid"]:
            games = games.filter(appid__in=options["appid"])
        if options["resume"]:
            games = games.exclude(insight__analysis_version=VERSION)
        ids = list(games.values_list("appid", flat=True))
        started = time.perf_counter()
        for offset in range(0, len(ids), 100):
            batch_ids = ids[offset:offset + 100]
            reviews = list(Review.objects.filter(game_id__in=batch_ids).order_by("game_id", "-votes_up", "id").values_list("game_id", "id", "text"))
            grouped = defaultdict(list)
            for (appid, review_id, _), points in zip(reviews, analyzer.pipe(text for _, _, text in reviews)):
                grouped[appid].append((review_id, points))
            batch = [GameInsight(game_id=appid, analysis_version=VERSION, analyzed_count=len(grouped[appid]), **aggregate(grouped[appid])) for appid in batch_ids]
            with transaction.atomic():
                GameInsight.objects.bulk_create(batch, update_conflicts=True, unique_fields=["game"], update_fields=["analysis_version", "analyzed_count", "positive", "negative", "prepared_at"])
            self.stdout.write(f"Prepared {min(offset + 100, len(ids)):,}/{len(ids):,} games in {time.perf_counter() - started:.1f}s", ending="\n")
        self.stdout.write(self.style.SUCCESS("Review insights ready. Games without reviews use an empty state."))
