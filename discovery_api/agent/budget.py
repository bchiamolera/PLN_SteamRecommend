"""A monotonic deadline shared by one complete local agent request."""
import time
from django.conf import settings
from .contracts import AgentError


class RequestBudget:
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.deadline = self.started + settings.AGENT_REQUEST_TIMEOUT

    def remaining(self):
        value = self.deadline - self.clock()
        if value <= 0:
            raise AgentError('deadline', 'The agent reached its overall time limit. Try a more specific request.', 504)
        return value

    def attempt_timeout(self):
        return min(settings.AGENT_ATTEMPT_TIMEOUT, self.remaining())
