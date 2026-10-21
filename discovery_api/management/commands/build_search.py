import time
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from discovery_api.models import DatasetState, Game
from discovery_api.management.commands.import_catalog import load_catalog
from steam_discovery.artifacts import fingerprint, save_bundle
from steam_discovery.preprocessing import english_stopwords
from steam_discovery.search import train_word2vec, document_vector

class Command(BaseCommand):
    help = "Train the original Word2Vec settings and atomically publish search artifacts."

    def add_arguments(self, parser):
        parser.add_argument("--catalog", default=str(settings.BASE_DIR / "_DadosLimpos/jogos_steam.pkl.gz"))

    def handle(self, *args, **options):
        started = time.perf_counter()
        state = DatasetState.objects.filter(key="catalog").first()
        if not state:
            raise CommandError("Run import_catalog first.")
        english_stopwords()
        digest = fingerprint(options["catalog"])
        if digest != state.fingerprint:
            raise CommandError("Catalog fingerprint changed. Run import_catalog before build_search.")
        df = load_catalog(options["catalog"])
        if set(df.appid.astype(int)) != set(Game.objects.values_list("appid", flat=True)):
            raise CommandError("Database game IDs differ from the catalog. Run import_catalog again.")
        sentences = df.description_tokens_sem_stopwords.tolist()
        self.stdout.write(f"Training Word2Vec on {len(df):,} descriptions (10 epochs, one worker)...", ending="\n")
        model = train_word2vec(sentences)
        vectors = np.vstack([document_vector(tokens, model.wv) for tokens in sentences])
        directory = save_bundle(settings.DISCOVERY_ARTIFACTS, model, vectors, df.appid.tolist(), digest)
        self.stdout.write(self.style.SUCCESS(f"Published {directory.name}; {time.perf_counter() - started:.1f}s."))
