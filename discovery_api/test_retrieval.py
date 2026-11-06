import json
import io
import math
import tempfile
from pathlib import Path
from unittest import TestCase as UnitTestCase
from unittest.mock import patch
import numpy as np
from django.test import TestCase, override_settings
from django.core.management import call_command
from rest_framework.test import APIClient
from steam_discovery.artifacts import SearchIndex, save_bundle, ArtifactError
from steam_discovery.lexical import BM25Index, PARAMETERS
from steam_discovery.filters import MetadataIndex, FilterError
from steam_discovery.search import train_word2vec, document_vector
from steam_discovery.retrieval import top_rows, reciprocal_rank_fusion
from steam_discovery.evaluation import validate_judgments, evaluate, dcg
from discovery_api.management.commands.relevance_benchmark import seeds
from discovery_api.models import Game, Review, GameInsight, DatasetState

RECORDS = [
    {'appid': 10, 'genres': ['Adventure'], 'user_tags': ['Co-op', 'Puzzle']},
    {'appid': 20, 'genres': ['Action'], 'user_tags': ['Co-op', 'Survival', 'Zombies']},
    {'appid': 30, 'genres': ['Simulation'], 'user_tags': ['Singleplayer', 'Farming']},
]

def enrich_fixture(directory):
    BM25Index.build(['Portal solve cooperative puzzles', 'Survivor survive zombies', 'QuietFarm grow crops']).save(directory)
    (directory / 'metadata.json').write_text(json.dumps(RECORDS))
    vectors = np.zeros((3, 384), dtype=np.float32)
    vectors[0, 0] = vectors[1, 1] = vectors[2, 2] = 1
    np.save(directory / 'sentence_vectors.npy', vectors)
    (directory / 'sentence_model').mkdir()
    (directory / 'sentence_model/config.json').write_text('{}')
    return {'bm25': PARAMETERS, 'sentence': {'model_id': 'sentence-transformers/all-MiniLM-L6-v2', 'max_tokens': 256, 'revision': 'fixture'}, 'metadata_version': 1}

class LexicalTests(UnitTestCase):
    def test_bm25_matches_hand_calculation_and_ignores_unknown_terms(self):
        index = BM25Index.build(['apple apple banana', 'banana'])
        expected = math.log(2) * 2 * 2.5 / (2 + 1.5 * (.25 + .75 * 3 / 2))
        np.testing.assert_allclose(index.scores('apple'), [expected, 0], rtol=1e-6)
        np.testing.assert_array_equal(index.scores('unknownterm'), [0, 0])
        np.testing.assert_allclose(index.scores('apple apple'), index.scores('apple'))

    def test_rrf_and_stable_appid_ties(self):
        result = reciprocal_rank_fusion([[0, 1], [1, 0]], np.array([20, 10]), 2)
        self.assertEqual([p for p, _ in result], [1, 0])
        self.assertAlmostEqual(result[0][1], 1/61 + 1/62)
        scores, ids = np.arange(300), np.arange(300)
        mask = np.zeros(300, dtype=bool); mask[0] = True
        self.assertEqual(top_rows(scores, ids, mask, 200).tolist(), [0])

    def test_strict_filters_and_label_validation(self):
        index = MetadataIndex(RECORDS)
        mask, normalized = index.eligible(required_tag=[' co-OP ', 'Puzzle'], genre=['Action', 'Adventure'])
        self.assertEqual(np.flatnonzero(mask).tolist(), [0])
        self.assertEqual(normalized['required_tag'], ['Co-op', 'Puzzle'])
        self.assertEqual(np.flatnonzero(index.eligible(excluded_tag=['Zombies'])[0]).tolist(), [0, 2])
        with self.assertRaises(FilterError): index.eligible(required_tag=['Unknown'])
        with self.assertRaises(FilterError): index.eligible(required_tag=['Puzzle'], excluded_tag=['puzzle'])
        self.assertFalse(index.eligible(required_tag=['Puzzle', 'Zombies'])[0].any())

class BundleTests(UnitTestCase):
    def test_upgrade_reuses_word2vec_and_filters_before_retrieval(self):
        model = train_word2vec([['solve', 'puzzles'], ['survive', 'zombies'], ['grow', 'crops']])
        vectors = np.vstack([document_vector(s, model.wv) for s in [['solve', 'puzzles'], ['survive', 'zombies'], ['grow', 'crops']]])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = save_bundle(root, model, vectors, [10, 20, 30], 'fixture')
            old = SearchIndex(root, 'fixture')
            self.assertEqual(old.retrieve('solve puzzles', 1)['matches'][0][0], 10)
            with self.assertRaises(ArtifactError): old.retrieve('solve', 10, 'bm25')
            before = (root / 'current').read_text()
            def fail(directory): raise RuntimeError('interrupted')
            with self.assertRaises(RuntimeError): save_bundle(root, None, None, [10, 20, 30], 'fixture', enrich=fail, reuse=old)
            self.assertEqual((root / 'current').read_text(), before)
            new = save_bundle(root, None, None, [10, 20, 30], 'fixture', enrich=enrich_fixture, reuse=old)
            self.assertEqual((original / 'vectors.npy').read_bytes(), (new / 'vectors.npy').read_bytes())
            index = SearchIndex(root, 'fixture')
            query = np.zeros(384, dtype=np.float32); query[0] = 1
            with patch('steam_discovery.sentence.encode_query', return_value=query), patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
                for mode in ('word2vec', 'bm25', 'sentence', 'hybrid_word2vec', 'hybrid_sentence'):
                    result = index.retrieve('solve puzzles Portal', 10, mode, {'required_tag': ['Puzzle']})
                    self.assertEqual([a for a, _ in result['matches']], [10])
                result = index.retrieve('solve', 1, 'sentence', {'excluded_tag': ['Puzzle']})
                self.assertEqual(result['matches'][0][0], 20)
                self.assertEqual(index.retrieve('Portal', 1, 'hybrid_word2vec')['matches'][0][0], 10)
                self.assertEqual(index.retrieve('unknownzz', 1, 'bm25')['matches'], [])
                self.assertEqual(index.retrieve('solve', 10, 'sentence', {'required_tag': ['Puzzle', 'Zombies']})['matches'], [])
            index.close(); old.close()

class UpgradeApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        Game.objects.create(appid=10, name='Portal')

    def test_repeated_filters_and_score_semantics(self):
        from types import SimpleNamespace
        calls = []
        def retrieve(q, limit, mode, filters):
            calls.append((mode, filters))
            return {'matches': [(10, .02)], 'score_type': 'rrf', 'filters': filters, 'known_terms': [], 'unknown_terms': [], 'message': ''}
        index = SimpleNamespace(retrieve=retrieve, metadata=MetadataIndex(RECORDS))
        with patch('discovery_api.views.search_index', return_value=index):
            response = self.client.get('/api/v1/search/?q=solve&mode=hybrid_sentence&required_tag=Co-op&required_tag=Puzzle&genre=Adventure&genre=Action')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls[0][1]['required_tag'], ['Co-op', 'Puzzle'])
            self.assertEqual(calls[0][1]['genre'], ['Adventure', 'Action'])
            self.assertIsNone(response.json()['results'][0]['similarity'])
            self.assertEqual(response.json()['results'][0]['score_type'], 'rrf')
            self.assertEqual(self.client.get('/api/v1/filters/').json()['tags'][0]['count'], 2)
        self.assertEqual(self.client.get('/api/v1/search/?q=solve&mode=unknown').status_code, 400)

    def test_bad_filter_is_400_and_missing_index_is_503(self):
        from types import SimpleNamespace
        def fail(*args): raise FilterError('Unknown tag')
        with patch('discovery_api.views.search_index', return_value=SimpleNamespace(retrieve=fail)):
            self.assertEqual(self.client.get('/api/v1/search/?q=solve&required_tag=unknown').status_code, 400)
        with patch('discovery_api.views.search_index', side_effect=ArtifactError('Rebuild search')):
            self.assertEqual(self.client.get('/api/v1/filters/').status_code, 503)

    def test_build_command_preserves_reviews_and_insights(self):
        import pandas as pd
        from types import SimpleNamespace
        from steam_discovery.artifacts import fingerprint
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / 'catalog.pkl.gz'
            pd.DataFrame([dict(appid=r['appid'], name=f'Game {r["appid"]}', description='solve puzzles', description_idioma='en', description_tokens_sem_stopwords=['solve', 'puzzles'], genres=r['genres'], user_tags=r['user_tags']) for r in RECORDS]).to_pickle(catalog)
            digest = fingerprint(catalog)
            for appid in [20, 30]: Game.objects.create(appid=appid, name=f'Game {appid}')
            Review.objects.create(id='preserve', game_id=10, text='Original review', voted_up=True)
            GameInsight.objects.create(game_id=10, analysis_version='original', analyzed_count=1)
            DatasetState.objects.create(key='catalog', fingerprint=digest)
            model = train_word2vec([['solve', 'puzzles']])
            vectors = np.vstack([document_vector(['solve'], model.wv)] * 3)
            save_bundle(root, model, vectors, [10, 20, 30], digest)
            cache = root / 'model_cache'; cache.mkdir()
            (cache / 'model.json').write_text(json.dumps({'model_id': 'sentence-transformers/all-MiniLM-L6-v2', 'revision': 'fixture'}))
            folder = cache / 'fixture'; folder.mkdir(); (folder / 'config.json').write_text('{}')
            fake = SimpleNamespace(tokenizer=lambda batch, **kwargs: {'input_ids': [[1, 2] for _ in batch]}, encode=lambda batch, **kwargs: np.tile(np.eye(1, 384, dtype=np.float32), (len(batch), 1)))
            with override_settings(DISCOVERY_ARTIFACTS=root), patch('discovery_api.management.commands.build_search.load_encoder', return_value=fake), patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
                call_command('build_search', catalog=str(catalog), reuse_word2vec=True, stdout=io.StringIO())
            index = SearchIndex(root, digest)
            self.assertEqual(index.manifest['schema_version'], 2)
            self.assertEqual(Review.objects.get(pk='preserve').text, 'Original review')
            self.assertEqual(GameInsight.objects.get(game_id=10).analysis_version, 'original')
            self.assertEqual(index.manifest['sentence']['truncated_descriptions'], 0)
            self.assertEqual(index.retrieve('puzzles', 10, 'bm25')['score_type'], 'bm25')
            index.close()

class EvaluationTests(UnitTestCase):
    def test_query_split_and_unjudged_are_not_zero(self):
        queries = seeds()
        self.assertEqual(len(queries), 60)
        self.assertEqual(sum(q['split'] == 'dev' for q in queries), 40)
        pool = [dict(query_id='a', appid=10), dict(query_id='a', appid=20)]
        rankings = {'methods': {'word2vec': {'a': [10, 20]}, 'bm25': {'a': [20, 10]}}, 'latency_seconds': {'word2vec': [.1], 'bm25': [.1]}, 'constraint_violations': {'word2vec': 0, 'bm25': 0}}
        cases = [dict(id='a', split='dev', category='example')]
        judgments = [dict(query_id='a', appid=10, grade=2, status='agent_draft')]
        report = evaluate(cases, pool, rankings, judgments, 'agent_draft', 'dev')
        self.assertEqual(report['incomplete_queries'], ['a'])
        self.assertIsNone(report['methods']['word2vec']['ndcg_at_10'])
        judgments.append(dict(query_id='a', appid=20, grade=0, status='agent_draft'))
        report = evaluate(cases, pool, rankings, judgments, 'agent_draft', 'dev')
        self.assertEqual(report['methods']['word2vec']['ndcg_at_10'], 1)
        self.assertLess(report['methods']['bm25']['ndcg_at_10'], 1)
        self.assertAlmostEqual(dcg([2, 0]), 3)

    def test_judgment_provenance_evidence_and_duplicate_checks(self):
        pool = [dict(query_id='a', appid=10, name='Portal', description='Puzzles', genres=[], user_tags=[])]
        row = dict(query_id='a', appid=10, grade=2, status='human_reviewed', reason='Reviewed', evidence={'field': 'name', 'quote': 'Portal'})
        with self.assertRaises(ValueError): validate_judgments([row], pool)
        self.assertEqual(validate_judgments([row], pool, True), [row])
        with self.assertRaises(ValueError): validate_judgments([row, row], pool, True)
        with self.assertRaises(ValueError): validate_judgments([{**row, 'grade': True}], pool, True)
        with self.assertRaises(ValueError): validate_judgments([{**row, 'evidence': {'field': 'name', 'quote': 'Invented'}}], pool, True)
