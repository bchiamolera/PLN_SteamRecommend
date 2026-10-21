import hashlib
import math
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count, Q, OuterRef, Subquery
from django.db.models.functions import Coalesce
from discovery_api.models import DatasetState, Game, GameInsight, Review
from steam_discovery.artifacts import fingerprint

def number(value):
    return max(0, int(value)) if pd.notna(value) and math.isfinite(float(value)) else 0

class Command(BaseCommand):
    help = "Import English reviews from a trusted cleaned pickle; stable IDs make reruns repeatable."

    def add_arguments(self, parser):
        parser.add_argument("--reviews", default=str(settings.BASE_DIR / "_DadosLimpos/steam_reviews.pkl.gz"))

    def handle(self, *args, **options):
        if not DatasetState.objects.filter(key="catalog").exists():
            raise CommandError("Run import_catalog first.")
        try:
            df = pd.read_pickle(options["reviews"])
            digest = fingerprint(options["reviews"])
        except (OSError, ValueError) as exc:
            raise CommandError("Cannot read the cleaned reviews; check --reviews.") from exc
        required = {"appid", "review", "review_idioma", "voted_up"}
        if not required.issubset(df.columns):
            raise CommandError(f"Review file is missing columns: {sorted(required - set(df.columns))}")
        ids = set(Game.objects.values_list("appid", flat=True))
        eligible = df.review_idioma.eq("en") & df.appid.isin(ids) & df.review.map(lambda x: isinstance(x, str) and bool(x.strip())) & df.voted_up.isin([True, False])
        columns = [c for c in ["appid", "review", "voted_up", "timestamp_created", "votes_up", "votes_funny", "weighted_vote_score", "playtime_forever"] if c in df.columns]
        df = df.loc[eligible, columns]
        with transaction.atomic():
            GameInsight.objects.all().delete()
            Review.objects.all().delete()
            batch = []
            for values in df.itertuples(index=False, name=None):
                row = dict(zip(columns, values))
                appid, text = int(row["appid"]), row["review"].strip()
                timestamp = number(row.get("timestamp_created", 0))
                identity = f"{appid}\0{timestamp}\0{text}"
                batch.append(Review(id=hashlib.sha256(identity.encode()).hexdigest(), game_id=appid, text=text, voted_up=bool(row["voted_up"]), timestamp_created=timestamp, votes_up=number(row.get("votes_up", 0)), metadata={k: (None if pd.isna(v) else float(v)) for k, v in row.items() if k in {"votes_funny", "weighted_vote_score", "playtime_forever"}}))
                if len(batch) >= 500:
                    Review.objects.bulk_create(batch, batch_size=500, ignore_conflicts=True)
                    batch.clear()
            Review.objects.bulk_create(batch, batch_size=500, ignore_conflicts=True)
            counts = Review.objects.filter(game_id=OuterRef("appid")).values("game_id").annotate(total=Count("id"), positive=Count("id", filter=Q(voted_up=True)))
            Game.objects.update(review_count=Coalesce(Subquery(counts.values("total")[:1]), 0), recommended_count=Coalesce(Subquery(counts.values("positive")[:1]), 0))
            DatasetState.objects.update_or_create(key="reviews", defaults={"fingerprint": digest, "metadata": {"count": Review.objects.count()}})
        self.stdout.write(self.style.SUCCESS(f"Imported {Review.objects.count():,} English reviews. Next: build_insights."))
