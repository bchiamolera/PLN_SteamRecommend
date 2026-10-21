import json
import random
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from discovery_api.models import Game, Review
from steam_discovery.insights import AspectAnalyzer, candidate_clauses, VERSION

class Command(BaseCommand):
    help = "Export 50 review clauses across five games for manual annotation, or score an annotated file."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--export")
        group.add_argument("--annotations")
        parser.add_argument("--output", help="Optional JSON report path when scoring annotations.")

    def handle(self, *args, **options):
        analyzer = AspectAnalyzer()
        if options["export"]:
            rows, games = [], 0
            rng = random.Random(42)
            for game in Game.objects.filter(review_count__gte=2).order_by("appid").iterator():
                candidates = []
                for review in Review.objects.filter(game=game).order_by("id"):
                    candidates.extend({"appid": game.appid, "game": game.name, "review_id": review.id, "text": text, "expected": None} for text in candidate_clauses(review.text))
                if len(candidates) < 10:
                    continue
                rows.extend(rng.sample(candidates, 10))
                games += 1
                if games == 5:
                    break
            if games < 5:
                raise CommandError("Need at least five games with ten aspect-bearing clauses each.")
            path = Path(options["export"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.stdout.write(f"Exported {len(rows)} clauses. Annotate expected as a list of {{aspect, polarity}}; use [] for neutral/ambiguous text.")
            return
        rows = json.loads(Path(options["annotations"]).read_text(encoding="utf-8"))
        if len(rows) < 50 or len({r["appid"] for r in rows}) < 5 or any(r.get("expected") is None for r in rows):
            raise CommandError("Annotate at least 50 clauses across five games before scoring.")
        emitted, correct, covered, gold = 0, 0, 0, 0
        errors = []
        for row, points in zip(rows, analyzer.pipe(r["text"] for r in rows)):
            expected = {(p["aspect"], p["polarity"]) for p in row["expected"]}
            predicted = {(p["aspect"], p["polarity"]) for p in points}
            emitted += len(predicted)
            correct += len(predicted & expected)
            gold += len(expected)
            covered += bool(predicted)
            if predicted - expected:
                errors.append({"review_id": row["review_id"], "text": row["text"], "predicted": sorted(predicted), "expected": sorted(expected)})
        report = {"analysis_version": VERSION, "clauses": len(rows), "games": len({r['appid'] for r in rows}), "predicted_points": emitted, "correct_points": correct, "precision": correct / emitted if emitted else None, "clause_coverage": covered / len(rows), "point_recall": correct / gold if gold else None, "false_positives": errors}
        serialized = json.dumps(report, indent=2)
        if options["output"]:
            Path(options["output"]).write_text(serialized + "\n", encoding="utf-8")
        self.stdout.write(serialized)
