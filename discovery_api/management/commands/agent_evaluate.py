"""Offline retrieval baseline, or explicitly opted-in paid chat evaluation."""
import json
import os
import time
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from discovery_api import services
from discovery_api.agent.chat import Chat
from discovery_api.agent.contracts import AgentError, ChatRequest, REGISTRY, validated
from discovery_api.agent.providers import create_provider
from discovery_api.agent.evaluation import evaluate_turn


class Command(BaseCommand):
    help = 'Evaluate fixed chat cases offline; --live requires explicit paid-call opt-in.'

    def add_arguments(self, parser):
        parser.add_argument('--cases', default=str(settings.BASE_DIR / 'validation/agent/chat_cases.json'))
        parser.add_argument('--judgments')
        parser.add_argument('--output')
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--allow-charges', action='store_true')
        parser.add_argument('--provider', choices=REGISTRY)
        parser.add_argument('--model')
        parser.add_argument('--key-env')
        parser.add_argument('--max-turns', type=int, default=20)

    def handle(self, *args, **options):
        if options['max_turns'] < 1:
            raise CommandError('max-turns must be positive.')
        live = options['live']
        key = ''
        if live:
            if not all(options[k] for k in ('allow_charges', 'provider', 'model', 'key_env')):
                raise CommandError('Live evaluation requires --allow-charges, --provider, --model and --key-env.')
            key = os.environ.get(options['key_env'], '').strip()
            if not key:
                raise CommandError('The named development-key variable is empty.')
        try:
            cases = json.loads(Path(options['cases']).read_text(encoding='utf-8'))
            judgments = json.loads(Path(options['judgments']).read_text(encoding='utf-8')) if options['judgments'] else []
        except (OSError, ValueError):
            raise CommandError('Cannot read evaluation cases or judgments.') from None
        rows, artifacts, count = [], [], 0
        for case in cases:
            history, context = [], {}
            for number, message in enumerate(case['messages']):
                if count >= options['max_turns']:
                    break
                count += 1
                if not live:
                    # Each message is an isolated retrieval baseline, not a simulated conversation.
                    started = time.monotonic()
                    result = services.search_catalog({'q': message, 'mode': 'hybrid_sentence', 'limit': 10, **case.get('filters', {})})
                    rows.append({'case_id': case['id'], 'turn': number, 'candidate_appids': [g['appid'] for g in result['results']],
                                 'status': 'offline_retrieval_only', 'final_appids': None,
                                 'filters': result['filters'],
                                 'elapsed_ms': round((time.monotonic() - started) * 1000),
                                 'semantic_support_rate': None, 'constraint_preservation': None})
                    continue
                client = None
                try:
                    params = validated(ChatRequest, {'provider': options['provider'], 'model': options['model'],
                        'message': message, 'history': history[-12:], 'context': context, 'filters': case.get('filters', {})})
                    client = create_provider(params['provider'], key)
                    runner = Chat(params, client)
                    result = runner.run()
                    rows.append(evaluate_turn(case['id'], number, result, runner.trace, client.diagnostics, judgments))
                    artifacts.append({'case_id': case['id'], 'turn': number, 'query': message, 'searches': runner.trace, 'response': result})
                    history.extend([{'role': 'user', 'content': message, 'appids': []},
                        {'role': 'assistant', 'content': result['reply'], 'appids': [g['appid'] for g in result['results']],
                         'games': [{'appid': g['appid'], 'explanation': g['explanation']} for g in result['results']]}])
                    context = result['context']
                except AgentError as exc:
                    rows.append({'case_id': case['id'], 'turn': number, 'status': 'error', 'code': exc.code,
                                 'diagnostics': dict(client.diagnostics) if client else {}})
                    break
                except Exception:
                    raise CommandError('Evaluation failed. Check local artifacts and request configuration.') from None
                finally:
                    if client:
                        client.close()
        manifest_path = settings.DISCOVERY_ARTIFACTS / 'current'
        bundle = manifest_path.read_text(encoding='ascii').strip() if manifest_path.exists() else None
        report = {'mode': 'live_chat' if live else 'offline_retrieval', 'quality_improvement_claimed': False,
                  'artifact_bundle': bundle,
                  'human_judgments_supplied': bool(judgments), 'turns_executed': count,
                  'turn_cap': options['max_turns'], 'rows': rows, 'review_artifacts': artifacts}
        output = json.dumps(report, indent=2, ensure_ascii=False)
        if key and key in output:
            raise CommandError('Credential validation failed.')
        if options['output']:
            Path(options['output']).write_text(output + '\n', encoding='utf-8')
        else:
            self.stdout.write(output)
