"""Request-local official SDK clients. Never log provider exceptions or credentials."""
import json
import time
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from dataclasses import dataclass, field
from .contracts import AgentError, REGISTRY, MODEL_SETTINGS
from .budget import RequestBudget


@dataclass
class Call:
    id: str
    name: str
    arguments: dict


@dataclass
class Turn:
    calls: list
    usage: dict = field(default_factory=dict)


def retry_after(exc):
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    value = headers.get('retry-after')
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


def provider_error(exc):
    code = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    if code in (401, 403):
        return AgentError('authentication', 'The provider rejected this key or its permissions.', 401)
    if code == 429:
        # Inspect structured codes only; never retain or echo provider messages.
        body = getattr(exc, 'body', None)
        if not isinstance(body, dict):
            body = getattr(exc, 'response_json', {})
        error = body.get('error', body) if isinstance(body, dict) else {}
        markers = {str(error.get(k, '')).lower() for k in ('code', 'type', 'status')} if isinstance(error, dict) else set()
        if markers & {'insufficient_quota', 'billing_hard_limit_reached', 'quota_exceeded', 'billing_not_active'}:
            return AgentError('quota_exhausted', 'Provider quota is exhausted. Check billing or quota before retrying.', 429)
        return AgentError('rate_limit', 'The provider is temporarily rate limited. Try again shortly.', 429, retry_after=retry_after(exc))
    if isinstance(exc, TimeoutError) or 'timeout' in type(exc).__name__.lower() or code in (408, 504):
        return AgentError('provider_timeout', 'The provider attempt timed out.', 504, retry_after=retry_after(exc))
    if code in (400, 404, 422):
        return AgentError('model_unavailable', 'The selected model or tool configuration is unavailable for this key.', 400)
    if isinstance(code, int) and (code >= 500 or code == 409):
        return AgentError('provider_failure', 'The provider is temporarily unavailable.', 502, retry_after=retry_after(exc))
    if isinstance(exc, ConnectionError) or type(exc).__name__ in ('APIConnectionError', 'ConnectError', 'ReadError', 'RemoteProtocolError'):
        return AgentError('connection', 'Cannot connect to the provider.', 502)
    return AgentError('internal_error', 'The provider response could not be processed. No retry was made.', 502)


def retry_requests(operation):
    @wraps(operation)
    def wrapped(self, *args, **kwargs):
        if not hasattr(self, 'budget'):
            self.budget = RequestBudget()
        if not hasattr(self, 'diagnostics'):
            self.diagnostics = {'attempts': 0, 'retries': 0}
        for attempt in range(6):
            self.request_timeout = self.budget.attempt_timeout()
            history = list(self.history)
            self.diagnostics['attempts'] += 1
            try:
                value = operation(self, *args, **kwargs)
                self.budget.remaining()
                return value
            except AgentError as exc:
                self.history = history
                if exc.code not in ('provider_timeout', 'provider_failure', 'rate_limit', 'connection'):
                    raise
                if attempt == 5:
                    raise AgentError(exc.code, exc.detail + ' Failed after 5 automatic retries.', exc.status) from None
                delay = exc.retry_after if exc.retry_after is not None else min(2 ** attempt, 8)
                if delay >= self.budget.remaining():
                    raise AgentError('deadline', 'Not enough time remains to retry this request.', 504) from None
                time.sleep(delay)
                self.diagnostics['retries'] += 1
    return wrapped


def plain(value):
    return value.model_dump(mode='json', exclude_none=True)


class Provider:
    def __init__(self, provider, key):
        self.provider, self.history = provider, []
        self.budget = RequestBudget()
        self.diagnostics = {'attempts': 0, 'retries': 0}
        # Explicit base URLs prevent environment overrides redirecting supplied keys.
        if provider == 'openai':
            from openai import OpenAI
            self.client = OpenAI(api_key=key, base_url='https://api.openai.com/v1', max_retries=0, timeout=self.budget.attempt_timeout())
        elif provider == 'anthropic':
            from anthropic import Anthropic
            self.client = Anthropic(api_key=key, base_url='https://api.anthropic.com', max_retries=0, timeout=self.budget.attempt_timeout())
        else:
            from google import genai
            from google.genai import types
            self.client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                base_url='https://generativelanguage.googleapis.com', timeout=int(self.budget.attempt_timeout() * 1000),
                retry_options=types.HttpRetryOptions(attempts=1)))

    def close(self):
        self.client.close()

    @retry_requests
    def models(self):
        try:
            ids = set()
            if self.provider == 'google':
                token = None
                while True:
                    config = {'http_options': {'timeout': max(1, int(self.budget.attempt_timeout() * 1000))}}
                    if token:
                        config['page_token'] = token
                    values = self.client.models.list(config=config)
                    if not hasattr(values, 'page'):  # Simple iterable test doubles.
                        ids.update(m.name.removeprefix('models/') for m in values)
                        break
                    ids.update(m.name.removeprefix('models/') for m in values.page)
                    token = values.config.get('page_token')
                    if not token:
                        break
            elif self.provider == 'anthropic':
                after = None
                while True:
                    options = {'after_id': after} if after else {}
                    values = self.client.with_options(timeout=self.budget.attempt_timeout()).models.list(**options)
                    if not hasattr(values, 'data'):
                        ids.update(m.id for m in values)
                        break
                    ids.update(m.id for m in values.data)
                    if values.has_more is not True:
                        break
                    after = values.last_id
                    if not after:
                        raise AgentError('internal_error', 'Invalid provider model pagination.')
            else:
                values = self.client.with_options(timeout=self.budget.attempt_timeout()).models.list()
                ids.update(m.id for m in values)
            return [{'id': m, 'label': MODEL_SETTINGS[m]['label']} for m in REGISTRY[self.provider]['models'] if m in ids]
        except AgentError:
            raise
        except Exception as exc:
            raise provider_error(exc) from None

    @retry_requests
    def respond(self, model, system, initial, tools, timeout, final_only=False):
        try:
            return self._respond(model, system, initial, tools, min(self.request_timeout, timeout) if timeout is not None else self.request_timeout, final_only)
        except AgentError:
            raise
        except (ValueError, TypeError, KeyError):
            raise AgentError('invalid_model_output', 'The model returned invalid tool arguments.') from None
        except Exception as exc:
            raise provider_error(exc) from None

    def _respond(self, model, system, initial, tools, timeout, final_only):
        settings = MODEL_SETTINGS[model]
        if self.provider == 'openai':
            if not self.history:
                self.history = [{'role': 'user', 'content': initial}]
            response = self.client.with_options(timeout=timeout).responses.create(
                model=model, instructions=system, input=self.history, store=False,
                max_output_tokens=4096, parallel_tool_calls=False,
                reasoning={'effort': settings['reasoning_effort']},
                tools=[{'type': 'function', **t, 'strict': True} for t in tools],
                tool_choice={'type': 'function', 'name': 'finish_discovery'} if final_only else 'required')
            # Preserve reasoning/encrypted continuation items, not just function calls.
            self.history.extend(plain(item) for item in response.output)
            calls = [Call(item.call_id, item.name, json.loads(item.arguments))
                     for item in response.output if item.type == 'function_call']
            usage = plain(response.usage) if response.usage else {}
            return Turn(calls, {'input_tokens': usage.get('input_tokens', 0), 'output_tokens': usage.get('output_tokens', 0)})
        if self.provider == 'anthropic':
            if not self.history:
                self.history = [{'role': 'user', 'content': initial}]
            response = self.client.with_options(timeout=timeout).messages.create(
                model=model, system=system, messages=self.history, max_tokens=4096,
                output_config={'effort': settings['effort']},
                tools=[{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters'], 'strict': True} for t in tools],
                tool_choice=REGISTRY['anthropic']['tool_choice'])
            self.history.append({'role': 'assistant', 'content': [plain(block) for block in response.content]})
            return Turn([Call(b.id, b.name, b.input) for b in response.content if b.type == 'tool_use'],
                        {'input_tokens': response.usage.input_tokens, 'output_tokens': response.usage.output_tokens})
        from google.genai import types
        if not self.history:
            self.history = [types.Content(role='user', parts=[types.Part.from_text(text=initial)])]
        response = self.client.models.generate_content(
            model=model, contents=self.history,
            config=types.GenerateContentConfig(
                system_instruction=system, max_output_tokens=4096,
                thinking_config=types.ThinkingConfig(thinking_level=settings['thinking_level']),
                http_options=types.HttpOptions(timeout=None if timeout is None else max(1, int(timeout * 1000)),
                                              retry_options=types.HttpRetryOptions(attempts=1)),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                tools=[types.Tool(function_declarations=[types.FunctionDeclaration(
                    name=t['name'], description=t['description'], parameters_json_schema=t['parameters']) for t in tools])],
                tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                    mode='ANY', allowed_function_names=['finish_discovery'] if final_only else [t['name'] for t in tools]))))
        if not response.candidates or not response.candidates[0].content:
            return Turn([])
        content = response.candidates[0].content
        self.history.append(content)  # Preserve thought signatures and every returned part.
        calls = [Call(str(i), p.function_call.name, dict(p.function_call.args or {}))
                 for i, p in enumerate(content.parts or []) if p.function_call]
        usage = response.usage_metadata
        return Turn(calls, {'input_tokens': usage.prompt_token_count or 0,
                            'output_tokens': (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)} if usage else {})

    def results(self, pairs):
        if self.provider == 'openai':
            self.history.extend({'type': 'function_call_output', 'call_id': c.id,
                                 'output': json.dumps(value)} for c, value in pairs)
        elif self.provider == 'anthropic':
            self.history.append({'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': c.id, 'content': json.dumps(value)} for c, value in pairs]})
        else:
            from google.genai import types
            self.history.append(types.Content(role='user', parts=[
                types.Part.from_function_response(name=c.name, response=value) for c, value in pairs]))


def create_provider(provider, key):
    try:
        return Provider(provider, key)
    except ImportError:
        raise AgentError('configuration', 'Install the provider SDKs from requirements.txt.', 503) from None
    except Exception as exc:
        raise provider_error(exc) from None
