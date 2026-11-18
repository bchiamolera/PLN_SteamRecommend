from unittest import TestCase
from unittest.mock import patch
from types import SimpleNamespace as NS
from discovery_api.agent.providers import provider_error
from discovery_api.agent.budget import RequestBudget
from discovery_api.agent.providers import Provider, retry_requests
from discovery_api.agent.contracts import AgentError

class RetryTests(TestCase):
    @patch('discovery_api.agent.providers.time.sleep')
    def test_five_retries_and_history_restoration(self, sleep):
        adapter = Provider.__new__(Provider)
        adapter.history = ['original']
        attempts = []
        @retry_requests
        def operation(client):
            self.assertEqual(client.history, ['original'])
            attempts.append(1)
            client.history.append('partial')
            raise AgentError('provider_failure', 'Unavailable', 502)
        with self.assertRaises(AgentError) as caught:
            operation(adapter)
        self.assertEqual(len(attempts), 6)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2, 4, 8, 8])
        self.assertIn('5 automatic retries', caught.exception.detail)

    @patch('discovery_api.agent.providers.time.sleep')
    def test_success_stops_retries_and_permanent_errors_fail_immediately(self, sleep):
        adapter = Provider.__new__(Provider)
        adapter.history = []
        attempts = []
        @retry_requests
        def operation(client):
            attempts.append(1)
            if len(attempts) < 3:
                raise AgentError('provider_timeout', 'Timeout', 504)
            return 'ok'
        self.assertEqual(operation(adapter), 'ok')
        self.assertEqual(len(attempts), 3)
        for code in ('authentication', 'model_unavailable', 'invalid_model_output'):
            sleep.reset_mock()
            @retry_requests
            def invalid(client):
                raise AgentError(code, 'Invalid')
            with self.assertRaises(AgentError):
                invalid(adapter)
            sleep.assert_not_called()

    def test_quota_and_programming_errors_are_not_transient(self):
        quota = NS(status_code=429, body={'error': {'code': 'insufficient_quota'}})
        self.assertEqual(provider_error(quota).code, 'quota_exhausted')
        self.assertEqual(provider_error(AttributeError('private')).code, 'internal_error')
        temporary = NS(status_code=429, response=NS(headers={'retry-after': '7'}))
        self.assertEqual(provider_error(temporary).retry_after, 7)

    @patch('discovery_api.agent.providers.time.sleep')
    def test_deadline_shared_across_retries_and_retry_after(self, sleep):
        clock = [0]
        adapter = Provider.__new__(Provider)
        adapter.history = []
        adapter.budget = RequestBudget(clock=lambda: clock[0])
        timeouts = []
        sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
        @retry_requests
        def operation(client):
            timeouts.append(client.request_timeout)
            clock[0] += client.request_timeout
            raise AgentError('provider_timeout', 'Timeout')
        with self.assertRaises(AgentError) as caught:
            operation(adapter)
        self.assertEqual(caught.exception.code, 'deadline')
        self.assertEqual(timeouts, [45, 45, 45, 38])
        self.assertEqual(clock[0], 180)
        self.assertEqual(adapter.diagnostics['attempts'], 4)

    @patch('discovery_api.agent.providers.time.sleep')
    def test_retry_after_exceeding_deadline_stops_without_sleep(self, sleep):
        adapter = Provider.__new__(Provider)
        adapter.history = []
        @retry_requests
        def operation(client):
            raise AgentError('rate_limit', 'Wait', 429, retry_after=3600)
        with self.assertRaises(AgentError) as caught:
            operation(adapter)
        self.assertEqual(caught.exception.code, 'deadline')
        sleep.assert_not_called()
