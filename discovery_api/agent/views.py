import json
import logging
import time
import uuid
from contextlib import suppress
from functools import wraps
from django.conf import settings
from django.db import DatabaseError
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from steam_discovery.artifacts import ArtifactError
from steam_discovery.filters import FilterError
from .contracts import AgentError, ModelRequest, DiscoveryRequest, ChatRequest, REGISTRY, validated
from .providers import create_provider
from .runner import Discovery
from .chat import Chat
from .budget import RequestBudget

logger = logging.getLogger('steam_atlas.agent')


def endpoint(methods):
    def decorate(fn):
        @wraps(fn)
        def guarded(request):
            client = None
            key = ''
            request_id = uuid.uuid4().hex
            started = time.monotonic()
            budget = RequestBudget()
            outcome = 'ready'
            try:
                if request.method == 'POST':
                    origin = request.headers.get('Origin', '')
                    same = f'{request.scheme}://{request.get_host()}'
                    allowed = {same, *settings.AGENT_ALLOWED_ORIGINS}
                    if origin not in allowed or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                        raise AgentError('origin_rejected', 'Agent requests must come from the local application.', 403)
                    key = request.headers.get('X-Agent-API-Key', '').strip()
                    if not key or len(key) > 512 or not key.isascii() or any(c.isspace() for c in key):
                        raise AgentError('invalid_input', 'Supply a valid provider API key.', 400)
                    # Explicit bounded request bodies; key is accepted only through the header.
                    if len(request.body) > (200000 if fn.__name__ == 'chat' else 20000):
                        raise AgentError('invalid_input', 'Agent request is too large.', 400)
                    schema = {'discover': DiscoveryRequest, 'chat': ChatRequest}.get(fn.__name__, ModelRequest)
                    params = validated(schema, request.data)
                    if key in json.dumps(params):
                        raise AgentError('invalid_input', 'Do not include credentials in discovery text or context.', 400)
                    client = create_provider(params['provider'], key)
                    client.budget = budget
                    result = fn(request, params, client)
                else:
                    result = fn(request)
                if key and key in json.dumps(result):
                    raise AgentError('invalid_model_output', 'The response failed credential validation.')
                return Response({**result, 'request_id': request_id})
            except AgentError as exc:
                outcome = exc.code
                return Response({'code': exc.code, 'detail': exc.detail, 'request_id': request_id}, status=exc.status)
            except (APIException, FilterError):
                outcome = 'invalid_input'
                return Response({'code': outcome, 'detail': 'Invalid agent request or conflicting filters.', 'request_id': request_id}, status=400)
            except (ArtifactError, RuntimeError, DatabaseError):
                outcome = 'artifacts_unavailable'
                return Response({'code': outcome, 'detail': 'Local catalog/search artifacts are unavailable. Check ordinary search and backend setup.', 'request_id': request_id}, status=503)
            except Exception:
                # Provider/SDK exceptions may contain headers or request details.
                outcome = 'internal_error'
                return Response({'code': outcome, 'detail': 'The agent encountered an internal error. No retry was made.', 'request_id': request_id}, status=502)
            finally:
                metrics = getattr(client, 'diagnostics', {}) if client else {}
                logger.info('agent_request %s', json.dumps({'request_id': request_id, 'outcome': outcome,
                    'elapsed_ms': round((time.monotonic() - started) * 1000),
                    **{name: metrics.get(name) for name in ('attempts', 'retries', 'tool_count', 'validation_category')}}))
                if client is not None:
                    with suppress(Exception):
                        client.close()
        view = api_view(methods)(guarded)

        @wraps(view)
        def uncached(*args, **kwargs):
            response = view(*args, **kwargs)
            response['Cache-Control'] = 'no-store'
            response['Vary'] = 'Origin'
            return response
        return uncached
    return decorate


@endpoint(['GET'])
def providers(request):
    return {'providers': [{'id': key, 'label': value['label']} for key, value in REGISTRY.items()]}


@endpoint(['POST'])
def models(request, params, client):
    return {'provider': params['provider'], 'models': client.models()}


@endpoint(['POST'])
def discover(request, params, client):
    return Discovery(params, client).run()


@endpoint(['POST'])
def chat(request, params, client):
    return Chat(params, client).run()
