import json
from django.conf import settings
from django.core.management.base import BaseCommand
from steam_discovery.sentence import MODEL_ID

class Command(BaseCommand):
    help = 'Explicitly download public MiniLM files and pin a revision for offline use.'

    def add_arguments(self, parser):
        parser.add_argument('--revision', default=None, help='Optional commit; the first run resolves main and saves its SHA.')

    def handle(self, *args, **options):
        from huggingface_hub import HfApi, snapshot_download
        root = settings.DISCOVERY_ARTIFACTS / 'model_cache'
        root.mkdir(parents=True, exist_ok=True)
        marker = root / 'model.json'
        previous = json.loads(marker.read_text()) if marker.exists() else {}
        revision = options['revision'] or previous.get('revision') or HfApi(token=False).model_info(MODEL_ID).sha
        directory = root / revision
        snapshot_download(MODEL_ID, revision=revision, local_dir=str(directory), token=False, allow_patterns=['*.json', '*.txt', '*.safetensors', '1_Pooling/*', '2_Normalize/*'])
        from steam_discovery.sentence import load_encoder
        load_encoder(directory)
        marker.write_text(json.dumps({'model_id': MODEL_ID, 'revision': revision}), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'MiniLM is available locally. Revision: {revision}'))
