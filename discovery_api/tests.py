import io
import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase as UnitTestCase
from unittest.mock import patch
import numpy as np
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from steam_discovery.artifacts import ArtifactError, SearchIndex, save_bundle
from steam_discovery.credentials import steam_api_key
from steam_discovery.insights import AspectAnalyzer, VERSION, aggregate
from steam_discovery.preprocessing import preprocess, normalizar
from steam_discovery.search import rank, train_word2vec, document_vector
from .models import DatasetState, Game, GameInsight, Review
from .services import _load_index

class SearchTests(UnitTestCase):
    def test_preprocessing_preserves_negation_and_normalizes_apostrophes(self):
        tokens = preprocess("The WORLD is not boring; I can't stop!")
        self.assertIn('world', tokens)
        self.assertIn('not', tokens)
        self.assertIn("can't", tokens)
        self.assertEqual(normalizar(["can’t"]), ["can't"])
        self.assertNotIn('the', tokens)

    def test_ranking_zero_rows_stable_ties_and_limits(self):
        indices, scores = rank([1, 0], np.array([[1, 0], [0, 0], [2, 0], [0, 1]], dtype=np.float32), 20)
        self.assertEqual(indices.tolist(), [0, 2, 3])
        np.testing.assert_allclose(scores, [1, 1, 0])
        with self.assertRaises(ValueError): rank([0, 0], np.eye(2))
        with self.assertRaises(ValueError): rank([1, 0], np.eye(2), True)

    def test_artifact_roundtrip_matches_notebook_cosine_and_rejects_tampering(self):
        from sklearn.metrics.pairwise import cosine_similarity
        sentences = [['world', 'build'], ['friends', 'survive'], ['puzzle', 'quiet']]
        model = train_word2vec(sentences)
        vectors = np.vstack([document_vector(s, model.wv) for s in sentences])
        with tempfile.TemporaryDirectory() as directory:
            bundle = save_bundle(directory, model, vectors, [10, 20, 30], 'test-fingerprint')
            index = SearchIndex(directory, 'test-fingerprint')
            matches, _, _ = index.search('world build', 10)
            query = document_vector(['world', 'build'], model.wv)
            expected = cosine_similarity(query.reshape(1, -1), vectors)[0]
            order = np.argsort(-expected, kind='stable')
            self.assertEqual([a for a, _ in matches], [10 * (i + 1) for i in order])
            np.testing.assert_allclose([s for _, s in matches], expected[order], atol=1e-6)
            self.assertEqual(index.search('zzzunknownword', 10)[0], [])
            with self.assertRaises(ArtifactError): SearchIndex(directory, 'wrong-fingerprint')
            np.save(bundle / 'appids.npy', np.array([30, 20, 10]))
            with self.assertRaises(ArtifactError): SearchIndex(directory, 'test-fingerprint')
            index.close()

class InsightTests(UnitTestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = AspectAnalyzer()

    def test_negation_and_mixed_aspects(self):
        points = self.analyzer.analyze('The graphics are beautiful but the controls are terrible. The story is not good.')
        self.assertIn(('graphics', 'positive'), [(p['aspect'], p['polarity']) for p in points])
        self.assertIn(('controls', 'negative'), [(p['aspect'], p['polarity']) for p in points])
        self.assertIn(('story', 'negative'), [(p['aspect'], p['polarity']) for p in points])

    def test_ambiguous_and_neutral_clauses_abstain(self):
        self.assertEqual(self.analyzer.analyze('The graphics make the controls terrible.'), [])
        self.assertEqual(self.analyzer.analyze('The story has three chapters.'), [])

    def test_genre_comparisons_hypotheticals_and_unrelated_praise_abstain(self):
        for text in [
            'Definitely worth playing for classic FPS fans!',
            'Blue Shift gameplay felt more engaging.',
            'An important character whose story spans three chapters.',
            'Far too complicated to make multiplayer enjoyable.',
            'The multiplayer would be great if it worked.',
            'The objectives were great because it certainly was not the gameplay.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(self.analyzer.analyze(text), [])

    def test_distinct_review_counts_and_opposing_views(self):
        positive = {'aspect': 'graphics', 'polarity': 'positive', 'excerpt': 'Beautiful graphics.'}
        negative = {'aspect': 'graphics', 'polarity': 'negative', 'excerpt': 'Terrible graphics.'}
        points = aggregate([('a', [positive, positive]), ('b', [positive]), ('c', [negative]), ('d', [negative])])
        self.assertEqual(points['positive'][0]['support_count'], 2)
        self.assertEqual(points['negative'][0]['support_count'], 2)
        self.assertEqual(aggregate([('a', [positive])]), {'positive': [], 'negative': []})

class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.game = Game.objects.create(appid=10, name='Island', description='Build with friends', review_count=2, recommended_count=1)

    def test_validation_and_missing_game(self):
        for query in ['', '   ', 'x' * 501]:
            self.assertEqual(self.client.get('/api/v1/search/', {'q': query}).status_code, 400)
        for limit in ['0', '51', 'foo', '1.5']:
            self.assertEqual(self.client.get('/api/v1/search/', {'q': 'world', 'limit': limit}).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/games/999/').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/games/999/insights/').status_code, 404)

    def test_offline_search_and_details_without_credentials(self):
        from types import SimpleNamespace
        index = SimpleNamespace(search=lambda q, k: ([(10, .8)], ['world'], []))
        with patch.dict(os.environ, {'STEAM_API_KEY': ''}), patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), patch('discovery_api.views.search_index', return_value=index):
            response = self.client.get('/api/v1/search/', {'q': 'world'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['results'][0]['appid'], 10)
            self.assertEqual(self.client.get('/api/v1/games/10/').json()['steam_url'], 'https://store.steampowered.com/app/10/')

    def test_unavailable_search_returns_503(self):
        with patch('discovery_api.views.search_index', side_effect=ArtifactError('Run build_search.')):
            self.assertEqual(self.client.get('/api/v1/search/', {'q': 'world'}).status_code, 503)

    def test_empty_insights_and_evidence_ownership(self):
        endpoint = '/api/v1/games/10/insights/'
        self.assertEqual(self.client.get(endpoint).json()['status'], 'not_prepared')
        reviews = [Review.objects.create(id=f'r{i}', game=self.game, text='Beautiful graphics.', voted_up=True) for i in range(2)]
        points = aggregate((r.id, self._points(r.text)) for r in reviews)
        GameInsight.objects.create(game=self.game, analysis_version=VERSION, analyzed_count=2, **points)
        response = self.client.get(endpoint).json()
        self.assertEqual(response['status'], 'ready')
        for e in response['positive'][0]['evidence']:
            review = Review.objects.get(pk=e['review_id'])
            self.assertEqual(review.game_id, 10)
            self.assertIn(e['excerpt'], review.text)
        self.game.review_count = 0; self.game.save()
        self.assertEqual(self.client.get(endpoint).json()['status'], 'no_reviews')

    @staticmethod
    def _points(text):
        return [{'aspect': 'graphics', 'polarity': 'positive', 'excerpt': text}]

    def test_offline_insight_preparation_and_resume(self):
        DatasetState.objects.create(key='reviews', fingerprint='fixture')
        for i, text in enumerate(['The graphics are beautiful.', 'Beautiful graphics!', 'The controls are terrible.', 'Terrible controls!']):
            Review.objects.create(id=f'fixture-{i}', game=self.game, text=text, voted_up=i < 2)
        self.game.review_count = 4
        self.game.save()
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            call_command('build_insights', stdout=io.StringIO())
        insight = GameInsight.objects.get(game=self.game)
        self.assertEqual(insight.analyzed_count, 4)
        self.assertEqual(insight.positive[0]['support_count'], 2)
        self.assertEqual(insight.negative[0]['support_count'], 2)
        for point in insight.positive + insight.negative:
            for evidence in point['evidence']:
                review = Review.objects.get(pk=evidence['review_id'])
                self.assertEqual(review.game_id, self.game.appid)
                self.assertIn(evidence['excerpt'], review.text)
        with patch('discovery_api.management.commands.build_insights.AspectAnalyzer') as analyzer:
            analyzer.return_value.pipe.side_effect = AssertionError('Resume must skip prepared games')
            call_command('build_insights', resume=True, stdout=io.StringIO())
        self.assertEqual(GameInsight.objects.get(game=self.game).prepared_at, insight.prepared_at)

    def test_imports_are_repeatable_and_invalidate_insights(self):
        import pandas as pd
        with tempfile.TemporaryDirectory() as directory, patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            catalog = Path(directory) / 'catalog.pkl.gz'
            reviews = Path(directory) / 'reviews.pkl.gz'
            pd.DataFrame([dict(appid=10, name='Island', description='World', genres='Adventure, Indie', user_tags=['Co-op'], description_idioma='en', description_tokens_sem_stopwords=['world'])]).to_pickle(catalog)
            pd.DataFrame([dict(appid=10, review='Great graphics.', review_idioma='en', voted_up=True), dict(appid=10, review='Great graphics.', review_idioma='en', voted_up=True), dict(appid=10, review='bonjour', review_idioma='fr', voted_up=True)]).to_pickle(reviews)
            call_command('import_catalog', catalog=str(catalog), stdout=io.StringIO())
            for _ in range(2): call_command('import_reviews', reviews=str(reviews), stdout=io.StringIO())
            self.assertEqual(Review.objects.count(), 1)
            self.assertEqual(Game.objects.get(pk=10).review_count, 1)
            self.assertEqual(Game.objects.get(pk=10).genres, ['Adventure', 'Indie'])
            call_command('import_catalog', catalog=str(catalog), stdout=io.StringIO())
            self.assertEqual(Review.objects.count(), 0)
            self.assertFalse(DatasetState.objects.filter(key='reviews').exists())

class CredentialTests(UnitTestCase):
    def test_missing_key_fails_only_when_required(self):
        with patch('steam_discovery.credentials.load_dotenv'), patch.dict(os.environ, {'STEAM_API_KEY': ''}):
            self.assertEqual(steam_api_key('Review import', required=False), '')
            with self.assertRaisesRegex(ValueError, 'Listing games requires STEAM_API_KEY'):
                steam_api_key('Listing games')

    def test_environment_precedence(self):
        with patch.dict(os.environ, {'STEAM_API_KEY': 'environment-test-key'}):
            self.assertEqual(steam_api_key('Listing games'), 'environment-test-key')
