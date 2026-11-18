import copy
import json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import TestCase as UnitTestCase
from unittest.mock import MagicMock, patch
from django.test import TestCase
from rest_framework.test import APIClient
from steam_discovery.filters import MetadataIndex
from steam_discovery.artifacts import ArtifactError
from discovery_api.models import Game, GameInsight
from discovery_api.agent.contracts import AgentError, REGISTRY, MODEL_SETTINGS, TOOLS, DiscoveryRequest, validated
from discovery_api.agent.providers import Call, Turn, Provider, provider_error
from discovery_api.agent.runner import Discovery

FILTERS = {'required_tag': ['Co-op'], 'excluded_tag': ['Horror'], 'genre': ['Adventure']}
GAME = {'appid': 10, 'name': 'Island Builders', 'description': 'Explore an island with friends.',
        'genres': ['Adventure'], 'user_tags': ['Co-op', 'Exploration'], 'rank': 1, 'score': .025,
        'score_type': 'rrf', 'similarity': None, 'steam_url': 'https://store.steampowered.com/app/10/',
        'review_count': 3, 'recommended_count': 2}
EVIDENCE = {'review_id': 'review-1', 'excerpt': 'The gameplay is great.'}


def search_call(filters=None):
    return Call('search', 'search_games', {'query': 'island', 'mode': 'hybrid_sentence',
                                          'filters': copy.deepcopy(filters if filters is not None else FILTERS)})


def finish_data(**updates):
    return {'status': 'ready', 'message': 'A candidate for your preferences.', 'preferences': ['Exploration'],
            'limitations': [], 'recommendations': [{'appid': 10, 'explanation': 'The catalog describes exploring an island with friends.',
                'references': [{'kind': 'catalog', 'field': 'description', 'review_id': '', 'excerpt': GAME['description']}]}], **updates}


def finish_call(**updates):
    return Call('finish', 'finish_discovery', finish_data(**updates))


class FakeProvider:
    def __init__(self, turns):
        self.turns = iter(turns)
        self.messages, self.outputs = [], []
        self.closed = False

    def respond(self, *args):
        self.messages.append(args)
        return Turn(next(self.turns), {'input_tokens': 10, 'output_tokens': 5})

    def results(self, values):
        self.outputs.extend(values)

    def close(self):
        self.closed = True

    def models(self):
        return [{'id': 'gpt-6-luna', 'label': 'gpt-6-luna'}]


class AgentTests(TestCase):
    def setUp(self):
        self.game = Game.objects.create(**{k: GAME[k] for k in ['appid', 'name', 'description', 'genres', 'user_tags', 'review_count', 'recommended_count']})
        GameInsight.objects.create(game=self.game, analysis_version='aspects-clauses-v3', analyzed_count=3,
                                   positive=[{'aspect': 'gameplay', 'support_count': 2, 'evidence': [EVIDENCE]}], negative=[])
        self.index = NS(metadata=MetadataIndex([
            {'appid': 10, 'genres': ['Adventure'], 'user_tags': ['Co-op', 'Exploration']},
            {'appid': 20, 'genres': ['Action'], 'user_tags': ['Horror']}]))
        self.index.retrieve = MagicMock(return_value={'matches': [(10, .025)], 'score_type': 'rrf',
            'known_terms': [], 'unknown_terms': [], 'filters': FILTERS, 'message': ''})
        self.patch_index = patch('discovery_api.services.search_index', return_value=self.index)
        self.patch_index.start()
        self.addCleanup(self.patch_index.stop)
        self.params = validated(DiscoveryRequest, {'provider': 'openai', 'model': 'gpt-6-luna', 'query': 'island', 'filters': FILTERS})

    def run_agent(self, turns):
        client = FakeProvider(turns)
        return Discovery(self.params, client).run(), client

    def test_discovery_preserves_ranking_filters_usage_and_context(self):
        result, client = self.run_agent([[search_call()], [Call('i', 'inspect_games', {'appids': [10]})], [finish_call()]])
        self.assertEqual(result['results'][0]['score'], .025)
        self.assertEqual(result['results'][0]['similarity'], None)
        self.assertEqual(result['results'][0]['insight_status'], 'ready')
        self.assertEqual(result['filters'], FILTERS)
        self.assertEqual(result['usage']['input_tokens'], 30)
        self.assertEqual(result['context']['previous_appids'], [10])
        self.assertEqual(self.index.retrieve.call_args.args[3], FILTERS)

    def test_cannot_remove_filters_or_widen_or_genres(self):
        invalid = copy.deepcopy(FILTERS)
        invalid['required_tag'] = []
        result, client = self.run_agent([[search_call(invalid)], [search_call()], [finish_call()]])
        self.assertIn('error', client.outputs[0][1])
        self.assertEqual(self.index.retrieve.call_count, 1)
        invalid = copy.deepcopy(FILTERS)
        invalid['genre'].append('Action')
        with self.assertRaises(AgentError):
            self.run_agent([[search_call(invalid)]] * 4)

    def test_fabricated_cross_game_and_uninspected_evidence_rejected(self):
        for ref in [dict(kind='catalog', field='description', review_id='', excerpt='Invented fact'),
                    dict(kind='review', field='', **EVIDENCE),
                    dict(kind='review', field='', review_id='another-game', excerpt=EVIDENCE['excerpt'])]:
            with self.subTest(ref=ref):
                item = finish_data()['recommendations'][0]
                item['references'] = [ref]
                with self.assertRaises(AgentError):
                    self.run_agent([[search_call()], [finish_call(recommendations=[item])],
                                    [finish_call(recommendations=[item])], [finish_call(recommendations=[item])]])

    def test_review_reference_valid_after_inspection_and_missing_insights_reported(self):
        item = finish_data()['recommendations'][0]
        item['references'] = [dict(kind='review', field='', **EVIDENCE)]
        result, _ = self.run_agent([[search_call()], [Call('i', 'inspect_games', {'appids': [10]})], [finish_call(recommendations=[item])]])
        self.assertEqual(result['results'][0]['references'][0]['review_id'], 'review-1')
        GameInsight.objects.all().delete()
        result, _ = self.run_agent([[search_call()], [Call('i', 'inspect_games', {'appids': [10]})], [finish_call()]])
        self.assertEqual(result['results'][0]['insight_status'], 'not_prepared')

    def test_unknown_tools_and_game_ids_and_changed_order_rejected(self):
        result, client = self.run_agent([[Call('x', 'shell', {'cmd': 'anything'})], [search_call()],
                                      [Call('i', 'inspect_games', {'appids': [99]})], [finish_call()]])
        self.assertIn('error', client.outputs[0][1])
        self.assertIn('error', client.outputs[2][1])
        duplicate = finish_data()['recommendations'] * 2
        with self.assertRaises(AgentError):
            self.run_agent([[search_call()], *[[finish_call(recommendations=duplicate)]] * 3])

    def test_clarification_empty_search_and_conflicting_initial_filters(self):
        result, _ = self.run_agent([[finish_call(status='needs_clarification', recommendations=[], message='Which setting do you prefer?')]])
        self.assertEqual(result['status'], 'needs_clarification')
        self.index.retrieve.return_value['matches'] = []
        result, _ = self.run_agent([[search_call()], [finish_call(status='no_matches', recommendations=[], message='Try fewer constraints.')]])
        self.assertEqual(result['status'], 'no_matches')
        self.params['filters']['required_tag'] = ['Horror']
        client = FakeProvider([])
        with self.assertRaises(ValueError):
            Discovery(self.params, client).run()
        self.assertEqual(client.messages, [])

    def test_budget_and_finalization_only_last_response(self):
        result, client = self.run_agent([[Call('f', 'get_filters', {})]] * 3 + [[finish_call(status='needs_clarification', message='What would you like?', recommendations=[])]])
        self.assertTrue(client.messages[-1][-1])
        self.assertEqual([t['name'] for t in client.messages[-1][-3]], ['finish_discovery'])
        with self.assertRaises(AgentError) as caught:
            self.run_agent([[Call(str(i), 'get_filters', {}) for i in range(7)]])
        self.assertEqual(caught.exception.code, 'budget_exceeded')

    def test_slow_call_exhausts_shared_deadline(self):
        clock = [0]
        class SlowProvider(FakeProvider):
            def respond(self, *args):
                clock[0] += 181
                return super().respond(*args)
        client = SlowProvider([[search_call()]])
        with self.assertRaises(AgentError) as caught:
            Discovery(self.params, client, clock=lambda: clock[0]).run()
        self.assertEqual(caught.exception.code, 'deadline')
        self.assertEqual(client.messages[0][-2], 45)
        self.assertEqual(len(client.messages), 1)

    def test_api_origins_validation_no_store_and_credential_lifecycle(self):
        client = APIClient()
        key = 'test-secret-key'
        path = '/api/v1/agent/discover/'
        self.assertEqual(client.get('/api/v1/agent/providers/')['Cache-Control'], 'no-store')
        rejected = client.post(path, self.params, format='json', HTTP_X_AGENT_API_KEY=key, HTTP_ORIGIN='https://evil.example')
        self.assertEqual(rejected.status_code, 403)
        fake = FakeProvider([[search_call()], [finish_call()]])
        with patch('discovery_api.agent.views.create_provider', return_value=fake) as factory:
            response = client.post(path, self.params, format='json', HTTP_X_AGENT_API_KEY=key, HTTP_ORIGIN='http://127.0.0.1:5173')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertNotIn(key, json.dumps(response.data))
        self.assertNotIn(key, str(fake.messages))
        self.assertTrue(fake.closed)
        factory.assert_called_once_with('openai', key)
        with patch('discovery_api.agent.views.create_provider') as factory:
            response = client.post(path, {**self.params, 'api_key': key}, format='json', HTTP_X_AGENT_API_KEY=key, HTTP_ORIGIN='http://testserver')
        self.assertEqual(response.status_code, 400)
        factory.assert_not_called()

    def test_provider_errors_and_artifacts_sanitized_and_closed(self):
        fake = FakeProvider([])
        with patch('discovery_api.agent.views.create_provider', return_value=fake), patch('discovery_api.services.search_index', side_effect=ArtifactError('internal path')):
            response = APIClient().post('/api/v1/agent/discover/', self.params, format='json', HTTP_X_AGENT_API_KEY='secret', HTTP_ORIGIN='http://testserver')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('internal path', str(response.data))
        self.assertTrue(fake.closed)

    def test_real_sdk_http_discovery_and_refinement_for_every_provider(self):
        import httpx
        from openai import OpenAI
        from anthropic import Anthropic
        import httpx2
        from google import genai
        from google.genai import types
        for name in REGISTRY:
            with self.subTest(provider=name):
                requests, generations = [], []
                model = REGISTRY[name]['models'][0]

                def handle(request):
                    requests.append(request)
                    if request.method == 'GET':
                        values = {'models': [{'name': 'models/' + model}]} if name == 'google' else {'data': [{'id': model}], 'has_more': False, 'object': 'list'}
                        return (httpx2.Response if name == 'anthropic' else httpx.Response)(200, json=values)
                    payload = json.loads(request.content)
                    generations.append(payload)
                    call = [search_call(), Call('inspect', 'inspect_games', {'appids': [10]}), finish_call()][(len(generations) - 1) % 3]
                    if name == 'openai':
                        value = {'id': 'resp', 'object': 'response', 'created_at': 1, 'model': model, 'status': 'completed',
                                 'output': [{'type': 'function_call', 'id': 'fc', 'call_id': call.id, 'name': call.name, 'arguments': json.dumps(call.arguments)}],
                                 'usage': {'input_tokens': 2, 'output_tokens': 3, 'total_tokens': 5}}
                    elif name == 'anthropic':
                        value = {'id': 'msg', 'type': 'message', 'role': 'assistant', 'model': model,
                                 'content': [{'type': 'tool_use', 'id': call.id, 'name': call.name, 'input': call.arguments}],
                                 'stop_reason': 'tool_use', 'usage': {'input_tokens': 2, 'output_tokens': 3}}
                    else:
                        value = {'candidates': [{'content': {'role': 'model', 'parts': [{'functionCall': {'name': call.name, 'args': call.arguments}, 'thoughtSignature': 'c2lnbmF0dXJl'}]}, 'finishReason': 'STOP'}],
                                 'usageMetadata': {'promptTokenCount': 2, 'candidatesTokenCount': 3}}
                    return (httpx2.Response if name == 'anthropic' else httpx.Response)(200, json=value)

                transport = (httpx2.MockTransport if name == 'anthropic' else httpx.MockTransport)(handle)
                if name == 'google':
                    def construct(**kw):
                        kw['http_options'].httpx_client = httpx.Client(transport=transport)
                        return genai_client(**kw)
                    genai_client = genai.Client
                    target, factory = 'google.genai.Client', construct
                else:
                    original = OpenAI if name == 'openai' else Anthropic
                    target = 'openai.OpenAI' if name == 'openai' else 'anthropic.Anthropic'
                    factory = lambda **kw: original(**kw, http_client=(httpx2.Client if name == 'anthropic' else httpx.Client)(transport=transport))
                with patch(target, side_effect=factory):
                    params = {**self.params, 'provider': name, 'model': model}
                    with patch('logging.Logger._log') as logs:
                        first_client = Provider(name, 'development-secret-key')
                        try:
                            self.assertEqual(first_client.models()[0]['id'], model)
                            first = Discovery(params, first_client).run()
                        finally:
                            first_client.close()
                        second_client = Provider(name, 'development-secret-key')
                        try:
                            second = Discovery({**params, 'query': 'More exploration', 'context': first['context']}, second_client).run()
                        finally:
                            second_client.close()
                        self.assertNotIn('development-secret-key', str(logs.call_args_list))
                self.assertEqual(first['filters'], FILTERS)
                self.assertEqual(second['results'][0]['appid'], 10)
                self.assertEqual(len(generations), 6)
                self.assertNotIn('development-secret-key', json.dumps(generations))
                self.assertTrue(all(r.url.host in ['api.openai.com', 'api.anthropic.com', 'generativelanguage.googleapis.com'] for r in requests))
                if name == 'google':
                    self.assertTrue(all(float(r.headers.get('X-Server-Timeout', 45)) <= 45 for r in requests))
                self.assertTrue(all(value is not None and value <= 45 for r in requests for value in r.extensions.get('timeout', {}).values()))


class ProviderTests(UnitTestCase):
    def setUp(self):
        wait = patch("discovery_api.agent.providers.time.sleep")
        wait.start()
        self.addCleanup(wait.stop)

    def provider(self, name):
        # Real SDK serialization/types are exercised separately through mock HTTP below.
        module = {'openai': 'openai.OpenAI', 'anthropic': 'anthropic.Anthropic', 'google': 'google.genai.Client'}[name]
        with patch(module) as factory:
            adapter = Provider(name, 'secret')
        adapter.client.with_options.return_value = adapter.client
        return adapter, factory

    def test_models_intersection_and_no_retries(self):
        for name in REGISTRY:
            with self.subTest(provider=name):
                adapter, factory = self.provider(name)
                first = REGISTRY[name]['models'][0]
                values = [NS(name='models/' + first), NS(name='models/unknown')] if name == 'google' else [NS(id=first), NS(id='unknown')]
                adapter.client.models.list.return_value = values
                self.assertEqual(adapter.models(), [{'id': first, 'label': MODEL_SETTINGS[first]['label']}])
                if name != 'google':
                    self.assertEqual(factory.call_args.kwargs['max_retries'], 0)
                    self.assertEqual(factory.call_args.kwargs['timeout'], 45)
                else:
                    self.assertEqual(factory.call_args.kwargs['http_options'].retry_options.attempts, 1)
                    self.assertLessEqual(factory.call_args.kwargs['http_options'].timeout, 45000)
                adapter.close()
                adapter.client.close.assert_called_once()

    def test_round_trip_continuation_and_finalization_all_providers(self):
        from openai.types.responses import Response as OpenAIResponse
        from anthropic.types import Message
        from google.genai import types
        for name in REGISTRY:
            with self.subTest(provider=name):
                adapter, _ = self.provider(name)
                if name == 'openai':
                    reply = OpenAIResponse.model_construct(output=[
                        NS(type='reasoning', model_dump=lambda **_: {'type': 'reasoning', 'id': 'reason', 'summary': []}),
                        NS(type='function_call', call_id='call', name='get_filters', arguments='{}',
                           model_dump=lambda **_: {'type': 'function_call', 'call_id': 'call', 'name': 'get_filters', 'arguments': '{}'})], usage=None)
                    adapter.client.responses.create.return_value = reply
                elif name == 'anthropic':
                    reply = Message.model_validate({'id': 'msg', 'type': 'message', 'role': 'assistant',
                        'model': 'fake', 'content': [{'type': 'tool_use', 'id': 'call', 'name': 'get_filters', 'input': {}}],
                        'stop_reason': 'tool_use', 'usage': {'input_tokens': 2, 'output_tokens': 3}})
                    adapter.client.messages.create.return_value = reply
                else:
                    reply = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role='model', parts=[
                        types.Part(function_call=types.FunctionCall(name='get_filters', args={}), thought_signature=b'signature')]))])
                    adapter.client.models.generate_content.return_value = reply
                turn = adapter.respond(REGISTRY[name]['models'][0], 'system', 'initial', TOOLS, 12)
                self.assertEqual(turn.calls[0].name, 'get_filters')
                adapter.results([(turn.calls[0], {'tags': []})])
                adapter.respond(REGISTRY[name]['models'][0], 'system', 'initial', TOOLS[-1:], 5, True)
                if name == 'google':
                    self.assertEqual(adapter.history[1].parts[0].thought_signature, b'signature')
                    config = adapter.client.models.generate_content.call_args.kwargs['config']
                    self.assertEqual(config.tool_config.function_calling_config.allowed_function_names, ['finish_discovery'])
                    self.assertTrue(config.automatic_function_calling.disable)
                    self.assertEqual(config.thinking_config.thinking_level.value.lower(), 'minimal')
                elif name == 'openai':
                    self.assertEqual(adapter.history[1]['type'], 'reasoning')
                    self.assertFalse(adapter.client.responses.create.call_args.kwargs['store'])
                    self.assertEqual(adapter.client.responses.create.call_args.kwargs['reasoning'], {'effort': 'none'})
                else:
                    self.assertEqual(adapter.history[2]['content'][0]['tool_use_id'], 'call')
                    kwargs = adapter.client.messages.create.call_args.kwargs
                    self.assertEqual(kwargs['tool_choice']['type'], 'auto')
                    self.assertTrue(kwargs['tools'][0]['strict'])
                    self.assertEqual(kwargs['output_config'], {'effort': 'low'})

    def test_light_models_are_available_only_when_listed_and_ordered_before_large_models(self):
        for name in REGISTRY:
            adapter, _ = self.provider(name)
            ids = REGISTRY[name]['models']
            adapter.client.models.list.return_value = [NS(name='models/' + m) if name == 'google' else NS(id=m)
                                                        for m in reversed(ids)]
            self.assertEqual([m['id'] for m in adapter.models()], ids)
        self.assertIn('gemini-3.1-flash-lite', REGISTRY['google']['models'])
        self.assertIn('gemini-3.5-flash-lite', REGISTRY['google']['models'])
        self.assertIn('gpt-5.4-mini', REGISTRY['openai']['models'])
        self.assertIn('gpt-6.1-terra', REGISTRY['openai']['models'])
        for name in REGISTRY:
            for model in REGISTRY[name]['models']:
                self.assertIn(model, MODEL_SETTINGS)
                data = validated(DiscoveryRequest, {'provider': name, 'model': model, 'query': 'island'})
                self.assertEqual(data['model'], model)

    def test_error_mapping_does_not_echo_exception(self):
        for name in REGISTRY:
            adapter, _ = self.provider(name)
            for code, expected in [(401, 'authentication'), (429, 'rate_limit'), (500, 'provider_failure'), (404, 'model_unavailable')]:
                exc = Exception('secret headers and credentials')
                exc.status_code = code
                adapter.client.models.list.side_effect = exc
                with self.assertRaises(AgentError) as caught:
                    adapter.models()
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(provider_error(TimeoutError()).code, 'provider_timeout')
        self.assertIn('timed out', provider_error(TimeoutError()).detail)

    def test_evaluation_fixture_has_all_categories(self):
        cases = json.loads((Path(__file__).resolve().parent.parent / 'validation/agent/cases.json').read_text())
        self.assertEqual({c['category'] for c in cases}, {'descriptive', 'exclusions', 'refinement', 'ambiguity', 'unsupported', 'missing_evidence', 'source_injection'})
        self.assertTrue(all(c['judgment_status'] == 'agent_draft' for c in cases))
