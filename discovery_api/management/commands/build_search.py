import time
import json
import os
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
import multiprocessing
import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from discovery_api.models import DatasetState, Game
from discovery_api.management.commands.import_catalog import load_catalog
from steam_discovery.artifacts import fingerprint, save_bundle
from steam_discovery.preprocessing import english_stopwords
from steam_discovery.search import train_word2vec, document_vector
from steam_discovery.artifacts import SearchIndex
from discovery_api.management.commands.import_catalog import labels
from steam_discovery.lexical import BM25Index, PARAMETERS
from steam_discovery.sentence import load_encoder, MODEL_ID, MAX_TOKENS, encode_documents_worker

class Command(BaseCommand):
    help = 'Prepare all five methods and publish v2 artifacts without modifying games or reviews.'

    def add_arguments(self, parser):
        parser.add_argument("--catalog", default=str(settings.BASE_DIR / "_DadosLimpos/jogos_steam.pkl.gz"))
        parser.add_argument('--reuse-word2vec', action='store_true')
        parser.add_argument('--batch-size', type=int, default=64)
        parser.add_argument('--resume-sentence-from', help='Interrupted preparation directory with a compatible sentence_progress.json.')
        parser.add_argument('--workers', type=int, default=1, help='Use 1 to 4 CPU processes for offline embeddings; query execution is unchanged.')

    def handle(self, *args, **options):
        started = time.perf_counter()
        if options['batch_size'] < 1: raise CommandError('--batch-size must be positive.')
        if not 1 <= options['workers'] <= 4: raise CommandError('--workers must be between 1 and 4.')
        state = DatasetState.objects.filter(key="catalog").first()
        if not state:
            raise CommandError("Run import_catalog first.")
        english_stopwords()
        digest = fingerprint(options["catalog"])
        if digest != state.fingerprint:
            raise CommandError("Catalog fingerprint changed. Run import_catalog before build_search.")
        marker = settings.DISCOVERY_ARTIFACTS / 'model_cache/model.json'
        if not marker.exists(): raise CommandError('Run prepare_sentence_model first. build_search never downloads models.')
        sentence_settings = json.loads(marker.read_text(encoding='utf-8'))
        model_path = marker.parent / sentence_settings['revision']
        full = load_catalog(options["catalog"])
        for column in ('genres', 'user_tags'):
            if column not in full: full[column] = ''
        df = full[['appid', 'name', 'description', 'genres', 'user_tags']].copy()
        if set(df.appid.astype(int)) != set(Game.objects.values_list("appid", flat=True)):
            raise CommandError("Database game IDs differ from the catalog. Run import_catalog again.")
        reuse = SearchIndex(settings.DISCOVERY_ARTIFACTS, digest) if options['reuse_word2vec'] else None
        if reuse and reuse.appids.tolist() != df.appid.tolist():
            reuse.close()
            raise CommandError('Catalog order differs from the existing Word2Vec index. Rebuild without --reuse-word2vec.')
        if reuse:
            model, vectors = None, None
        else:
            self.stdout.write(f'Training Word2Vec on {len(df):,} descriptions...')
            model = train_word2vec(full.description_tokens_sem_stopwords.tolist())
            vectors = np.vstack([document_vector(tokens, model.wv) for tokens in full.description_tokens_sem_stopwords])
        del full
        def enrich(directory):
            import psutil
            records = [{'appid': int(r.appid), 'genres': labels(r.genres), 'user_tags': labels(r.user_tags)} for r in df.itertuples(index=False)]
            self.stdout.write('Preparing BM25 over names, genres, tags, and descriptions...')
            documents = ('\n'.join([str(row.name), ' '.join(meta['genres']), ' '.join(meta['user_tags']), str(row.description)]) for row, meta in zip(df.itertuples(index=False), records))
            BM25Index.build(documents).save(directory)
            (directory / 'metadata.json').write_text(json.dumps(records, ensure_ascii=False), encoding='utf-8')
            encoder = load_encoder(model_path) if options['workers'] == 1 else None
            truncated = 0
            progress = {'catalog_fingerprint': digest, 'revision': sentence_settings['revision'], 'count': len(df), 'max_tokens': MAX_TOKENS, 'completed_rows': 0, 'truncated': 0}
            if options['resume_sentence_from']:
                source = Path(options['resume_sentence_from'])
                previous = json.loads((source / 'sentence_progress.json').read_text(encoding='utf-8'))
                if any(previous[k] != progress[k] for k in ('catalog_fingerprint', 'revision', 'count', 'max_tokens')) or not np.array_equal(np.load(source / 'appids.npy', allow_pickle=False), df.appid.values):
                    raise CommandError('MiniLM checkpoint does not match the catalog, IDs, or model revision.')
                if not 0 <= previous['completed_rows'] <= len(df): raise CommandError('Checkpoint row count is out of bounds.')
                shutil.copy2(source / 'sentence_vectors.npy', directory / 'sentence_vectors.npy')
                progress = previous
                embeddings = np.lib.format.open_memmap(directory / 'sentence_vectors.npy', mode='r+')
                if embeddings.shape != (len(df), 384): raise CommandError('Invalid checkpoint dimensions.')
            else:
                embeddings = np.lib.format.open_memmap(directory / 'sentence_vectors.npy', mode='w+', dtype=np.float32, shape=(len(df), 384))
            texts = df.description.fillna('').astype(str).tolist()
            truncated = progress['truncated']
            # The encoder sorts each chunk internally to reduce padding while
            # returning vectors in their original input order.
            chunks = [(start, texts[start:start + 8192]) for start in range(progress['completed_rows'], len(texts), 8192)]
            with (ProcessPoolExecutor(max_workers=options['workers'], mp_context=multiprocessing.get_context('spawn')) if options['workers'] > 1 else nullcontext()) as executor:
                if executor:
                    outputs = executor.map(encode_documents_worker, ((str(model_path.resolve()), batch, options['batch_size']) for _, batch in chunks))
                else:
                    def sequential():
                        for _, batch in chunks:
                            tokens = encoder.tokenizer(batch, truncation=False, add_special_tokens=True)['input_ids']
                            yield encoder.encode(batch, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False, batch_size=options['batch_size']), sum(len(t) > MAX_TOKENS for t in tokens)
                    outputs = sequential()
                for (start, batch), (encoded, n_truncated) in zip(chunks, outputs):
                    truncated += n_truncated
                    embeddings[start:start + len(batch)] = encoded
                    embeddings.flush()
                    progress.update(completed_rows=start + len(batch), truncated=truncated)
                    temporary = directory / 'sentence_progress.tmp'
                    temporary.write_text(json.dumps(progress), encoding='utf-8')
                    os.replace(temporary, directory / 'sentence_progress.json')
                    self.stdout.write(f'MiniLM: {start + len(batch):,}/{len(texts):,}')
            embeddings.flush(); embeddings._mmap.close()
            if not np.isfinite(np.load(directory / 'sentence_vectors.npy', mmap_mode='r')).all():
                raise CommandError('MiniLM embeddings contain invalid values.')
            shutil.copytree(model_path, directory / 'sentence_model', ignore=shutil.ignore_patterns('.cache'))
            return {'bm25': PARAMETERS, 'metadata_version': 1, 'sentence': {**sentence_settings, 'max_tokens': MAX_TOKENS, 'dimensions': 384, 'truncated_descriptions': truncated}, 'preparation_seconds': round(time.perf_counter() - started, 3), 'preparation_rss_mb': round(psutil.Process().memory_info().rss / 1024**2, 1)}
        try:
            directory = save_bundle(settings.DISCOVERY_ARTIFACTS, model, vectors, df.appid.tolist(), digest, enrich=enrich, reuse=reuse)
        finally:
            if reuse: reuse.close()
        self.stdout.write(self.style.SUCCESS(f"Published {directory.name}; {time.perf_counter() - started:.1f}s."))
