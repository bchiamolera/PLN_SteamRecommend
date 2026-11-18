import os
import math
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or "local-academic-demo-only"
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
AGENT_ALLOWED_ORIGINS = ['http://127.0.0.1:5173', 'http://localhost:5173',
                         'http://127.0.0.1:4173', 'http://localhost:4173']
AGENT_ATTEMPT_TIMEOUT = float(os.environ.get('AGENT_ATTEMPT_TIMEOUT', '45'))
AGENT_REQUEST_TIMEOUT = float(os.environ.get('AGENT_REQUEST_TIMEOUT', '180'))
if not all(math.isfinite(value) and value > 0 for value in (AGENT_ATTEMPT_TIMEOUT, AGENT_REQUEST_TIMEOUT)):
    raise ValueError('Agent timeouts must be positive.')
LOGGING = {
    'version': 1, 'disable_existing_loggers': False,
    'handlers': {'agent_console': {'class': 'logging.StreamHandler'}},
    'loggers': {'steam_atlas.agent': {'handlers': ['agent_console'], 'level': 'INFO', 'propagate': False}},
}
INSTALLED_APPS = ["django.contrib.contenttypes", "rest_framework", "discovery_api"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "webconfig.urls"
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("DISCOVERY_DATABASE") or BASE_DIR / "db.sqlite3", "OPTIONS": {"timeout": 60}}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
DISCOVERY_ARTIFACTS = Path(os.environ.get("DISCOVERY_ARTIFACTS") or BASE_DIR / "artifacts")
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}
