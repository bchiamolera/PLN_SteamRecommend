import hashlib
import json
import os
import time
from pathlib import Path
from unittest.mock import patch
import psutil
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from discovery_api.models import Game
from discovery_api.services import search_index
from steam_discovery.evaluation import validate_judgments, draft_judgment, evaluate
from steam_discovery.filters import canonical
from steam_discovery.retrieval import MODES, CANDIDATES, RRF_K

def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

def write_lines(path, rows):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
    os.replace(temporary, path)

def seeds():
    groups = {
        'descriptive': ['Explore an open world and build a base to survive with friends', 'A relaxing farming game in a small village', 'A detective adventure about solving a mysterious crime', 'A story about difficult choices and their consequences', 'Build a city and manage its economy', 'Explore space and trade between planets', 'A frightening adventure with puzzles and a strong atmosphere', 'A tactical game with turn based battles', 'A fast arcade game with short sessions', 'Run a restaurant and serve customers', 'Explore ancient ruins and solve environmental puzzles', 'A colorful platform game with precise movement', 'A fantasy adventure with character progression', 'Manage a colony and keep its people alive', 'A peaceful exploration game without fighting', 'A game about sailing and discovering islands', 'Build automated factories and production lines', 'A narrative adventure about friendship and loss', 'Survive winter by collecting food and building shelter', 'A sports game to play with friends'],
        'exact_title': ['Portal 2', 'Half-Life 2', 'Stardew Valley', 'Terraria', 'Hades', 'Celeste', 'Dota 2', 'Counter-Strike 2', 'Euro Truck Simulator 2', 'The Witcher 3: Wild Hunt'],
        'mechanics': ['Solve puzzles together with a friend', 'Defend a base by building towers', 'Race cars on challenging tracks', 'A fishing simulation', 'Build complex automated factories', 'Turn based strategy battles', 'A visual novel with choices', 'Explore a metroidvania world', 'A roguelike dungeon crawler', 'Play a rhythm game with music'],
        'filters': ['Survive and build a base with friends', 'Cooperative puzzles without zombies', 'Explore a fantasy world with character progression', 'A single player mystery adventure', 'A racing game without horror', 'A strategy game without zombies', 'A relaxing adventure without horror', 'Survival games without zombies', 'A puzzle game with a story', 'A cooperative adventure'],
        'rare_terms': ['cooperativ survial base bilding', 'metroidvania exploration', 'deckbuilding roguelike', 'dieselpunk airship adventure', 'sokoban puzzle'],
        'hard': ['zzqxvplmnonexistentword', 'Survive with friends without building a base', 'An adventure without combat or violence', 'A game about time travel with no puzzles', 'Cooperative horror without zombies'],
    }
    tag_intents = [['Co-op', 'Puzzle'], ['Tower Defense'], ['Racing'], ['Fishing'], ['Automation'], ['Turn-Based Strategy'], ['Visual Novel'], ['Metroidvania'], ['Roguelike'], ['Rhythm']]
    filters = [dict(required_tag=['Co-op', 'Survival']), dict(required_tag=['Co-op', 'Puzzle'], excluded_tag=['Zombies']), dict(genre=['RPG']), dict(required_tag=['Singleplayer'], genre=['Adventure']), dict(genre=['Racing'], excluded_tag=['Horror']), dict(genre=['Strategy'], excluded_tag=['Zombies']), dict(genre=['Adventure'], excluded_tag=['Horror']), dict(required_tag=['Survival'], excluded_tag=['Zombies']), dict(genre=['Adventure', 'Indie'], required_tag=['Puzzle']), dict(required_tag=['Co-op'], genre=['Adventure'])]
    rows = []
    for category, texts in groups.items():
        for i, text in enumerate(texts):
            number = len(rows) + 1
            row = {'id': f'q{number:03d}', 'q': text, 'category': category, 'split': 'test' if number % 3 == 0 else 'dev', 'filters': {}, 'expected_behavior': 'Rank by relevance to the query intent; structured constraints are mandatory.'}
            if category == 'mechanics': row['intent_tags'] = tag_intents[i]
            if category == 'filters': row['filters'] = filters[i]
            if category == 'hard' and i == 0: row['no_interpretable_intent'] = True
            rows.append(row)
    return rows

class Command(BaseCommand):
    help = 'Initialize queries, export a blinded pool, draft labels, validate imports, freeze settings, and evaluate.'

    def add_arguments(self, parser):
        parser.add_argument('stage', choices=['init', 'export', 'draft', 'import', 'freeze', 'evaluate'])
        parser.add_argument('--directory', default='validation/relevance')
        parser.add_argument('--input')
        parser.add_argument('--confirm-human-review', action='store_true')
        parser.add_argument('--label-source', choices=['agent_draft', 'human_reviewed'], default='agent_draft')
        parser.add_argument('--split', choices=['dev', 'test'], default='dev')

    def handle(self, *args, **options):
        root = Path(options['directory']); root.mkdir(parents=True, exist_ok=True)
        index = search_index(); index.require_upgrade()
        config = {'catalog_fingerprint': index.manifest['dataset_fingerprint'], 'bundle': index.directory.name, 'bm25': index.manifest['bm25'], 'sentence': index.manifest['sentence'], 'rrf_k': RRF_K, 'candidates': CANDIDATES}
        code_files = ['artifacts.py', 'search.py', 'lexical.py', 'filters.py', 'sentence.py', 'retrieval.py', 'preprocessing.py']
        config['retrieval_code_sha256'] = hashlib.sha256(b''.join((settings.BASE_DIR / 'steam_discovery' / name).read_bytes() for name in code_files)).hexdigest()
        stage = options['stage']
        queries_path = root / 'queries.json'
        if stage == 'init':
            if queries_path.exists(): raise CommandError('queries.json already exists. Use another --directory to preserve judgments.')
            queries = seeds()
            for q in queries: index.metadata.eligible(**q['filters'])
            queries_path.write_text(json.dumps({'schema_version': 1, 'catalog_fingerprint': config['catalog_fingerprint'], 'queries': queries}, ensure_ascii=False, indent=2), encoding='utf-8')
            self.stdout.write('Created 60 fixed queries: 40 development, 20 test.'); return
        data = json.loads(queries_path.read_text(encoding='utf-8'))
        if data['catalog_fingerprint'] != config['catalog_fingerprint']: raise CommandError('The catalog changed. Create a new benchmark.')
        queries = data['queries']
        config['queries_sha256'] = hashlib.sha256(queries_path.read_bytes()).hexdigest()
        if stage == 'export':
            if (root / 'rankings.json').exists(): raise CommandError('Rankings already exist. Use another directory to avoid incompatible pools and judgments.')
            client, pool = Client(), []
            rankings = {'config': config, 'methods': {m: {} for m in MODES}, 'latency_seconds': {m: [] for m in MODES}, 'constraint_violations': {m: 0 for m in MODES}}
            with patch.dict(os.environ, {'STEAM_API_KEY': ''}), patch('socket.socket.connect', side_effect=AssertionError('Network access is forbidden during the benchmark')):
                for mode in MODES:
                    response = client.get('/api/v1/search/', {'q': 'open world adventure', 'mode': mode})
                    if response.status_code != 200: raise CommandError(str(response.json()))
                for count, query in enumerate(queries, 1):
                    ids = set()
                    for mode in MODES:
                        from urllib.parse import urlencode
                        params = {'q': query['q'], 'mode': mode, 'limit': 10, **query['filters']}
                        started = time.perf_counter()
                        response = client.get('/api/v1/search/?' + urlencode(params, doseq=True))
                        rankings['latency_seconds'][mode].append(time.perf_counter() - started)
                        if response.status_code != 200: raise CommandError(f"{query['id']} {mode}: {response.json()}")
                        results = response.json()['results']
                        rankings['methods'][mode][query['id']] = [r['appid'] for r in results]
                        for r in results:
                            tags, genres = set(map(canonical, r['user_tags'])), set(map(canonical, r['genres']))
                            f = query['filters']
                            invalid = not set(map(canonical, f.get('required_tag', []))) <= tags or bool(set(map(canonical, f.get('excluded_tag', []))) & tags) or bool(f.get('genre') and not set(map(canonical, f['genre'])) & genres)
                            rankings['constraint_violations'][mode] += int(invalid)
                            ids.add(r['appid'])
                    games = Game.objects.in_bulk(ids)
                    pool.extend({'query_id': query['id'], 'appid': appid, 'name': games[appid].name, 'description': games[appid].description, 'genres': games[appid].genres, 'user_tags': games[appid].user_tags} for appid in sorted(ids))
                    self.stdout.write(f"Pool: {count}/60 queries")
            rankings['runtime_rss_mb'] = round(psutil.Process().memory_info().rss / 1024**2, 1)
            write_lines(root / 'pool.jsonl', pool)
            rankings['pool_sha256'] = hashlib.sha256((root / 'pool.jsonl').read_bytes()).hexdigest()
            (root / 'rankings.json').write_text(json.dumps(rankings, indent=2), encoding='utf-8')
            self.stdout.write(f'Exported {len(pool)} query/game pairs without method names or scores in the pool.'); return
        rankings = json.loads((root / 'rankings.json').read_text())
        if rankings['config'] != config: raise CommandError('Settings, bundle, queries, or code differ from the export. Create a new benchmark.')
        if rankings['pool_sha256'] != hashlib.sha256((root / 'pool.jsonl').read_bytes()).hexdigest(): raise CommandError('The candidate pool changed. Preserve the original blinded data.')
        pool = read_lines(root / 'pool.jsonl')
        if stage == 'draft':
            if (root / 'judgments.jsonl').exists(): raise CommandError('Judgments already exist. Existing reviews will not be overwritten.')
            by_id = {q['id']: q for q in queries}
            rows = [draft_judgment(c, by_id[c['query_id']]) for c in pool]
            validate_judgments(rows, pool)
            write_lines(root / 'judgments.jsonl', rows)
            self.stdout.write('Created rule-assisted drafts; other pairs remain unjudged.'); return
        if stage == 'import':
            if not options['input']: raise CommandError('Provide --input with the reviewed JSONL file.')
            try: rows = validate_judgments(read_lines(Path(options['input'])), pool, options['confirm_human_review'])
            except (ValueError, KeyError, TypeError) as exc: raise CommandError(str(exc)) from None
            write_lines(root / 'judgments.jsonl', rows); return
        if stage == 'freeze':
            (root / 'freeze.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
            self.stdout.write('Settings frozen. This does not constitute human approval of judgments.'); return
        if options['split'] == 'test':
            freeze = root / 'freeze.json'
            if not freeze.exists() or json.loads(freeze.read_text()) != config: raise CommandError('Freeze the configuration before evaluating the test split: relevance_benchmark freeze')
        rows = validate_judgments(read_lines(root / 'judgments.jsonl'), pool, confirm_human=True)
        report = evaluate(queries, pool, rankings, rows, options['label_source'], options['split'])
        report['runtime_rss_mb'] = rankings['runtime_rss_mb']
        path = root / f"report_{options['split']}_{options['label_source']}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
