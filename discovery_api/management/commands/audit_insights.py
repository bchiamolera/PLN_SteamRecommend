import json
from itertools import islice
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Sum
from discovery_api.models import Game, GameInsight, Review
from steam_discovery.insights import VERSION

class Command(BaseCommand):
    help = "Verify all prepared evidence against its original review and game."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="validation/evidence_audit.json")

    def handle(self, *args, **options):
        queryset = GameInsight.objects.filter(analysis_version=VERSION).select_related("game").order_by("game_id")
        iterator = queryset.iterator(chunk_size=500)
        checked = 0
        errors = []
        while batch := list(islice(iterator, 500)):
            refs = [e["review_id"] for insight in batch for side in (insight.positive, insight.negative) for point in side for e in point["evidence"]]
            reviews = Review.objects.in_bulk(refs)
            for insight in batch:
                if insight.analyzed_count != insight.game.review_count:
                    errors.append(f"Review coverage mismatch for {insight.game_id}")
                for side in (insight.positive, insight.negative):
                    if len(side) > 5:
                        errors.append(f"Too many points for {insight.game_id}")
                    for point in side:
                        if not 2 <= point["support_count"] <= insight.analyzed_count or not 1 <= len(point["evidence"]) <= 3:
                            errors.append(f"Invalid support/evidence count for {insight.game_id}")
                        for evidence in point["evidence"]:
                            review = reviews.get(evidence["review_id"])
                            if review is None or review.game_id != insight.game_id or evidence["excerpt"] not in review.text:
                                errors.append(f"Invalid evidence for {insight.game_id}: {evidence['review_id']}")
                            checked += 1
        games_with_reviews = Game.objects.filter(review_count__gt=0).count()
        prepared = queryset.count()
        report = {"analysis_version": VERSION, "games_with_reviews": games_with_reviews, "prepared_games": prepared, "analyzed_reviews": queryset.aggregate(total=Sum("analyzed_count"))["total"] or 0, "imported_reviews": Review.objects.count(), "checked_excerpts": checked, "errors": errors, "complete": prepared == games_with_reviews}
        path = Path(options["output"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        self.stdout.write(json.dumps(report, indent=2))
        if errors or not report["complete"]:
            raise CommandError("Insight audit incomplete or failed; see the JSON report.")
