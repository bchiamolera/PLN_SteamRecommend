import io
import json
from unittest.mock import patch, MagicMock
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase
from discovery_api.agent.evaluation import evaluate_turn


class EvaluationTests(SimpleTestCase):
    def test_unreviewed_is_unknown_and_draft_never_counts_as_human(self):
        result = {'results': [{'appid': 10}], 'kind': 'recommendations'}
        draft = {'case_id': 'c01', 'turn': 0, 'appid': 10, 'relevant': True,
                 'supported': True, 'source': 'agent_draft', 'reviewer': 'agent'}
        row = evaluate_turn('c01', 0, result, [{'candidate_appids': [10]}], {}, [draft])
        self.assertTrue(row['selection_from_search'])
        self.assertIsNone(row['relevant_game_rate'])
        self.assertIsNone(row['semantic_support_rate'])
        self.assertEqual(row['unreviewed_games'], 1)
        row = evaluate_turn('c01', 0, result, [], {}, [{**draft, 'source': 'human_reviewed', 'reviewer': 'Reviewer A'}])
        self.assertEqual(row['relevant_game_rate'], 1)
        self.assertEqual(row['semantic_support_rate'], 1)

    @patch('discovery_api.management.commands.agent_evaluate.create_provider')
    @patch('discovery_api.management.commands.agent_evaluate.services.search_catalog')
    def test_offline_is_capped_and_makes_no_provider_calls(self, search, factory):
        search.return_value = {'results': [{'appid': 10}], 'filters': {}}
        output = io.StringIO()
        call_command('agent_evaluate', max_turns=2, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['turns_executed'], 2)
        self.assertEqual(search.call_count, 2)
        factory.assert_not_called()
        self.assertFalse(result['quality_improvement_claimed'])

    @patch('discovery_api.management.commands.agent_evaluate.create_provider')
    def test_live_requires_explicit_opt_in(self, factory):
        with self.assertRaises(CommandError):
            call_command('agent_evaluate', live=True)
        factory.assert_not_called()

    @patch.dict('os.environ', {'TEST_EVAL_KEY': 'private-test-key'})
    @patch('discovery_api.management.commands.agent_evaluate.Chat')
    @patch('discovery_api.management.commands.agent_evaluate.create_provider')
    def test_live_cap_and_chat_history(self, factory, runner):
        client = MagicMock(diagnostics={'attempts': 1, 'retries': 0})
        factory.return_value = client
        runner.return_value.trace = []
        runner.return_value.run.return_value = {'kind': 'needs_clarification', 'reply': 'What setting?',
                                               'context': {}, 'results': []}
        output = io.StringIO()
        call_command('agent_evaluate', live=True, allow_charges=True, provider='google',
                     model='gemini-3.1-flash-lite', key_env='TEST_EVAL_KEY', max_turns=3, stdout=output)
        self.assertEqual(factory.call_count, 3)
        self.assertEqual(len(runner.call_args.args[0]['history']), 2)
        self.assertNotIn('private-test-key', output.getvalue())
        self.assertEqual(client.close.call_count, 3)
