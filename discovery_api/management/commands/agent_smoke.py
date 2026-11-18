"""Explicitly opt-in live discovery/refinement smoke test, never run by ordinary tests."""
import json
import os
from contextlib import suppress
from django.core.management.base import BaseCommand, CommandError
from django.core.management import call_command
from discovery_api.agent.contracts import AgentError, DiscoveryRequest, REGISTRY, validated
from discovery_api.agent.providers import create_provider
from discovery_api.agent.runner import Discovery


class Command(BaseCommand):
    help = 'Run a paid live agent search and refinement using an explicitly named development-key environment variable.'

    def add_arguments(self, parser):
        parser.add_argument('--provider', choices=REGISTRY, required=True)
        parser.add_argument('--model', required=True)
        parser.add_argument('--key-env', required=True)
        parser.add_argument('--allow-charges', action='store_true')
        parser.add_argument('--query', default='Explore an island with friends')
        parser.add_argument('--chat', action='store_true', help='Run the fixed conversational evaluation scenarios.')
        parser.add_argument('--max-turns', type=int, default=20)

    def handle(self, *args, **options):
        if not options['allow_charges']:
            raise CommandError('Live smoke requires --allow-charges; provider usage is billed to your development key.')
        key = os.environ.get(options['key_env'], '').strip()
        if not key:
            raise CommandError('The explicitly named development-key variable is empty.')
        if options['chat']:
            return call_command('agent_evaluate', live=True, allow_charges=True,
                provider=options['provider'], model=options['model'], key_env=options['key_env'],
                max_turns=options['max_turns'], stdout=self.stdout)
        client = None
        try:
            params = validated(DiscoveryRequest, {'provider': options['provider'], 'model': options['model'], 'query': options['query']})
            client = create_provider(params['provider'], key)
            models = client.models()
            if params['model'] not in {m['id'] for m in models}:
                raise CommandError('The selected model was not listed for this key.')
            first = Discovery(params, client).run()
            client.close()
            client = create_provider(params['provider'], key)
            second = Discovery({**params, 'query': 'More exploration', 'filters': first['filters'], 'context': first['context']}, client).run()
            output = json.dumps({'discovery': first, 'refinement': second}, ensure_ascii=False)
            if key in output:
                raise CommandError('Credential validation failed.')
            self.stdout.write(output)
        except AgentError as exc:
            raise CommandError(f'{exc.code}: {exc.detail}') from None
        except CommandError:
            raise
        except Exception:
            raise CommandError('Smoke failed; check local artifacts, request settings and provider access.') from None
        finally:
            if client:
                with suppress(Exception):
                    client.close()
