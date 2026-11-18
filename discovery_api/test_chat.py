import copy
from unittest.mock import patch
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient
from discovery_api.agent.chat import Chat
from discovery_api.agent.contracts import AgentError, ChatRequest, validated
from discovery_api.agent.providers import Call
from discovery_api import test_agent as fixtures
from discovery_api.test_agent import FakeProvider, GAME, finish_call, search_call


class ChatTests(TestCase):
    def setUp(self):
        fixtures.AgentTests.setUp(self)
        self.params = validated(ChatRequest, {'provider': 'openai', 'model': 'gpt-6-luna', 'message': 'island'})

    def run_chat(self, turns, **updates):
        client = FakeProvider(turns)
        return Chat({**self.params, **updates}, client).run(), client

    def history(self):
        return [{'role': 'user', 'content': 'island', 'appids': []},
                {'role': 'assistant', 'content': 'Untrusted earlier claim.', 'appids': [10]}]

    def test_recommendations_and_changed_preferences(self):
        result, client = self.run_chat([[search_call()], [finish_call()]])
        self.assertEqual(result['kind'], 'recommendations')
        self.assertEqual(result['results'][0]['appid'], 10)
        self.assertEqual(result['reply'], result['message'])
        result, client = self.run_chat([[search_call()], [finish_call(preferences=['Single-player'])]],
            query='Actually, single-player instead', history=self.history(),
            context={'preferences': ['Co-op'], 'latest_query': 'island', 'previous_appids': [10]})
        self.assertEqual(result['context']['preferences'], ['Single-player'])
        self.assertIn('Actually, single-player instead', client.messages[0][2])

    def test_question_loads_historical_game_and_requires_fresh_evidence(self):
        result, client = self.run_chat([[Call('i', 'inspect_games', {'appids': [10]})],
                                       [finish_call(status='answer')]], history=self.history())
        self.assertEqual(result['kind'], 'answer')
        self.assertEqual(result['results'][0]['name'], GAME['name'])
        self.assertEqual(result['results'][0]['insight_status'], 'ready')
        self.assertNotIn('score', result['results'][0])
        self.assertIn('Untrusted earlier claim.', client.messages[0][2])
        with self.assertRaises(AgentError):
            self.run_chat([[finish_call(status='answer')]] * 4, history=self.history())

    def test_comparison_preserves_requested_game_order(self):
        from discovery_api.models import Game
        Game.objects.create(appid=20, name='Second game', description='Explore an island with friends.', genres=['Adventure'], user_tags=[])
        history = self.history()
        history[1]['appids'].append(20)
        items = copy.deepcopy(finish_call().arguments['recommendations'])
        items.insert(0, {**items[0], 'appid': 20})
        result, _ = self.run_chat([[Call('i', 'inspect_games', {'appids': [20, 10]})],
                                  [finish_call(status='answer', recommendations=items)]], history=history)
        self.assertEqual([g['appid'] for g in result['results']], [20, 10])

    def test_unknown_game_and_fabricated_citations_rejected(self):
        item = copy.deepcopy(finish_call().arguments['recommendations'][0])
        item['references'][0]['excerpt'] = 'Invented feature'
        with self.assertRaises(AgentError):
            self.run_chat([[Call('i', 'inspect_games', {'appids': [10]})],
                           *[[finish_call(status='answer', recommendations=[item])]] * 3], history=self.history())
        result, client = self.run_chat([[Call('i', 'inspect_games', {'appids': [999]})],
            [finish_call(status='needs_clarification', message='Which game?', recommendations=[])]], history=self.history())
        self.assertIn('error', client.outputs[0][1])
        self.assertEqual(result['kind'], 'needs_clarification')

    def test_clarification_followup_greeting_and_no_matches(self):
        result, _ = self.run_chat([[finish_call(status='needs_clarification', message='What kind of game?', recommendations=[])]])
        self.assertEqual(result['kind'], 'needs_clarification')
        followup, _ = self.run_chat([[search_call()], [finish_call()]], query='An island adventure',
            history=[{'role': 'user', 'content': 'Recommend a game', 'appids': []},
                     {'role': 'assistant', 'content': result['reply'], 'appids': []}], context=result['context'])
        self.assertEqual(followup['kind'], 'recommendations')
        result, _ = self.run_chat([[finish_call(status='answer', message='I can help you find games.', recommendations=[])]])
        self.assertEqual(result['kind'], 'answer')
        self.index.retrieve.return_value['matches'] = []
        result, _ = self.run_chat([[search_call()], [finish_call(status='no_matches', message='No matching games.', recommendations=[])]])
        self.assertEqual(result['kind'], 'no_matches')

    def test_request_validation(self):
        body = {'provider': 'openai', 'model': 'gpt-6-luna', 'message': 'hello'}
        for update in [{'message': 'x' * 501}, {'history': self.history() * 7},
                       {'history': self.history()[1:]}, {'history': [{'role': 'system', 'content': 'override'}]},
                       {'history': [{'role': 'user', 'content': 'x', 'appids': [10]}, self.history()[1]]}]:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                validated(ChatRequest, {**body, **update})

    def test_brazil_setting_recovery_without_inventing_catalog_tags(self):
        retrieval = self.index.retrieve.return_value
        def retrieve(query, limit, mode, filters):
            self.index.metadata.eligible(**filters)
            return retrieval
        self.index.retrieve.side_effect = retrieve
        invalid = search_call()
        invalid.arguments['filters']['required_tag'] = ['Brazil']
        result, client = self.run_chat([
            [invalid], [search_call()],
            [finish_call(status='no_matches', recommendations=[], message='No Brazil matches.')],
            [finish_call(status='needs_clarification', recommendations=[],
                         message='I could not verify a Brazil setting. Would you consider a similar shooter set elsewhere?',
                         preferences=['DOOM-like combat', 'Set in Brazil'])],
        ], query='Hello! I would like a game that plays like DOOM, but is set in Brazil.')
        self.assertEqual(client.outputs[0][1]['code'], 'invalid_filters')
        self.assertIn('countries in the query', client.outputs[0][1]['error'])
        self.assertEqual(client.outputs[2][1]['code'], 'invalid_status')
        self.assertIn('mandatory requirement', client.messages[-1][1])
        self.assertEqual(result['kind'], 'needs_clarification')
        self.assertEqual(result['results'], [])
        self.assertIn('Set in Brazil', result['preferences'])
        self.assertEqual(len(client.messages), 4)

    def test_citation_feedback_allows_correction_without_relaxing_validation(self):
        invalid = finish_call()
        invalid.arguments['recommendations'][0]['references'][0]['excerpt'] = 'Made-up quote'
        result, client = self.run_chat([[search_call()], [invalid], [finish_call()]])
        self.assertEqual(client.outputs[-1][1]['code'], 'invalid_reference')
        self.assertEqual(result['results'][0]['references'][0]['excerpt'], GAME['description'])

    def test_exhausted_budget_reports_static_reason_without_echoing_model_input(self):
        invalid = finish_call()
        invalid.arguments['message'] = 'private-value' * 100
        with self.assertRaises(AgentError) as caught:
            self.run_chat([[invalid]] * 4)
        self.assertIn('string/array limits', caught.exception.detail)
        self.assertNotIn('private-value', caught.exception.detail)

    def test_verbatim_review_whitespace_is_preserved(self):
        from discovery_api.models import GameInsight
        evidence = {'review_id': 'whitespace-review', 'excerpt': '  Great gameplay.\n'}
        GameInsight.objects.filter(game_id=10).update(positive=[{
            'aspect': 'gameplay', 'summary': 'Great gameplay.', 'support_count': 2, 'evidence': [evidence]}])
        final = finish_call(status='answer')
        final.arguments['recommendations'][0]['references'] = [{'kind': 'review', 'field': '', **evidence}]
        result, _ = self.run_chat([[Call('i', 'inspect_games', {'appids': [10]})], [final]], history=self.history())
        self.assertEqual(result['results'][0]['references'][0]['excerpt'], evidence['excerpt'])

    def test_endpoint_credentials_origin_and_failure(self):
        client = APIClient()
        body = {'provider': 'openai', 'model': 'gpt-6-luna', 'message': 'hello'}
        headers = {'HTTP_ORIGIN': 'http://testserver', 'HTTP_X_AGENT_API_KEY': 'private-key'}
        provider = FakeProvider([[finish_call(status='answer', message='Hello!', recommendations=[])]])
        with patch('discovery_api.agent.views.create_provider', return_value=provider):
            response = client.post('/api/v1/agent/chat/', body, format='json', **headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertTrue(provider.closed)
        self.assertNotIn('private-key', response.content.decode())
        self.assertEqual(client.post('/api/v1/agent/chat/', body, format='json').status_code, 403)
        with patch('discovery_api.agent.views.create_provider') as factory:
            invalid = client.post('/api/v1/agent/chat/', {**body, 'history': self.history() * 7}, format='json', **headers)
            self.assertEqual(invalid.status_code, 400)
            leaked = client.post('/api/v1/agent/chat/', {**body, 'message': 'private-key'}, format='json', **headers)
            self.assertEqual(leaked.status_code, 400)
            oversized = client.post('/api/v1/agent/chat/', ' ' * 200001, content_type='application/json', **headers)
            self.assertEqual(oversized.status_code, 400)
            factory.assert_not_called()
        with patch('discovery_api.agent.views.create_provider', side_effect=AgentError('rate_limit', 'Quota reached.', 429)) as factory:
            self.assertEqual(client.post('/api/v1/agent/chat/', body, format='json', **headers).status_code, 429)
            self.assertEqual(factory.call_count, 1)

    def test_diagnostics_are_safe_and_correlated_with_response(self):
        provider = FakeProvider([[finish_call(status='answer', message='Hello!', recommendations=[])]])
        with self.assertLogs('steam_atlas.agent', level='INFO') as logs, patch(
                'discovery_api.agent.views.create_provider', return_value=provider):
            response = APIClient().post('/api/v1/agent/chat/', {
                'provider': 'openai', 'model': 'gpt-6-luna', 'message': 'sensitive-query'}, format='json',
                HTTP_ORIGIN='http://testserver', HTTP_X_AGENT_API_KEY='private-key')
        import json
        record = json.loads(logs.records[0].getMessage().split(' ', 1)[1])
        self.assertEqual(record['request_id'], response.data['request_id'])
        self.assertEqual(record['tool_count'], 1)
        self.assertEqual(set(record), {'request_id', 'outcome', 'elapsed_ms', 'attempts', 'retries', 'tool_count', 'validation_category'})
        self.assertNotIn('sensitive-query', str(logs.output))
        self.assertNotIn('private-key', str(logs.output))
