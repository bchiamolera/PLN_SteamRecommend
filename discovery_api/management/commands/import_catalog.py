import json
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from discovery_api.models import DatasetState, Game
from steam_discovery.artifacts import fingerprint

def labels(value):
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except ValueError:
        pass
    return [v.strip() for v in value.replace(";", ",").split(",") if v.strip()]

def load_catalog(path):
    df = pd.read_pickle(path)  # Trusted local project exports only.
    required = {"appid", "name", "description", "description_idioma", "description_tokens_sem_stopwords"}
    if not required.issubset(df.columns):
        raise CommandError(f"Catalog is missing columns: {sorted(required - set(df.columns))}")
    if df.empty or not df.description_idioma.eq("en").all() or df.appid.duplicated().any():
        raise CommandError("Expected a nonempty English catalog with unique appids. Re-run data cleaning.")
    if not df.description_tokens_sem_stopwords.map(lambda x: isinstance(x, list)).all():
        raise CommandError("Catalog tokens must be lists. Re-run data cleaning.")
    return df.reset_index(drop=True)

class Command(BaseCommand):
    help = "Import the trusted cleaned game catalog. Reimport invalidates review insights."

    def add_arguments(self, parser):
        parser.add_argument("--catalog", default=str(settings.BASE_DIR / "_DadosLimpos/jogos_steam.pkl.gz"))

    def handle(self, *args, **options):
        try:
            df = load_catalog(options["catalog"])
            digest = fingerprint(options["catalog"])
        except (OSError, ValueError) as exc:
            raise CommandError("Cannot read the cleaned catalog; check --catalog.") from exc
        # Stage validation before replacing data, then publish in one transaction.
        with transaction.atomic():
            Game.objects.all().delete()
            batch = []
            for row in df.to_dict("records"):
                batch.append(Game(appid=int(row["appid"]), name=str(row["name"]), description=str(row["description"]), genres=labels(row.get("genres")), user_tags=labels(row.get("user_tags"))))
                if len(batch) >= 500:
                    Game.objects.bulk_create(batch, batch_size=500)
                    batch.clear()
            Game.objects.bulk_create(batch, batch_size=500)
            DatasetState.objects.update_or_create(key="catalog", defaults={"fingerprint": digest, "metadata": {"count": len(df)}})
            DatasetState.objects.filter(key="reviews").delete()
        self.stdout.write(self.style.SUCCESS(f"Imported {len(df):,} games. Next: import_reviews, build_search, build_insights."))
