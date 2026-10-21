# Steam Atlas: local web demo

The Django REST API serves prepared Steam data to a separate React application.
Search uses the original 190-dimensional Word2Vec model. Review points use
spaCy dependencies and VADER; they are extractive observations, not generated summaries.

## Windows setup

Run these PowerShell commands from the repository root. Python 3.12 and a current
Node LTS release are recommended. Existing notebooks remain available.

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m nltk.downloader stopwords
.venv/Scripts/python.exe manage.py migrate
```

The download commands are setup steps only. The web application never downloads
models or contacts Steam while serving requests. `requirements.txt` is sufficient
for running and pins the official spaCy English model to 3.8.0 with its wheel checksum;
`requirements-dev.txt` adds notebook-parity testing dependencies.

Use only trusted project pickle exports: pandas pickle loading executes Python
serialization code. Dataset files and generated artifacts are intentionally ignored
by Git and must be copied separately when moving the demo to another computer.

## Prepare data (once)

```powershell
.venv/Scripts/python.exe manage.py import_catalog
.venv/Scripts/python.exe manage.py import_reviews
.venv/Scripts/python.exe -u manage.py build_search
.venv/Scripts/python.exe -u manage.py build_insights --resume
```

Defaults read `_DadosLimpos/jogos_steam.pkl.gz` and `steam_reviews.pkl.gz`.
Use `--catalog PATH` consistently for import_catalog/build_search and `--reviews PATH`
for import_reviews to select other trusted exports. Preserve the same cleaned English
schema. Search training uses vector_size=190, window=5, min_count=1, Skip-gram,
seed=42, workers=1, epochs=10, exactly as the original notebook.

`import_catalog` replaces catalog data and clears reviews/insights; rerun all subsequent
steps. `import_reviews` replaces reviews and invalidates insights; rerun build_insights.
Imports publish in database transactions. Review IDs hash appid, timestamp, and text;
exact repeated records are deduplicated. Counts refer to this collected English sample,
which was originally sampled by the collection notebooks, not all Steam reviews.

`build_insights --resume` skips games already prepared with the current analysis version.
It processes every imported review and saves after each batch of 100 games. For a short demonstration,
use `--appid 10 --appid 20` to prepare selected games first; the UI explicitly labels
other games as pending. Run the unrestricted command to finish the full corpus.
Do not run imports concurrently with preparation commands.

Artifacts are published to a new version directory before atomically switching
`artifacts/current`. SHA-256 file checksums, catalog fingerprint, preprocessing version,
training settings, and ordered game IDs are validated on first load. Each backend
process caches the active index; a new bundle or catalog fingerprint changes the cache key.
Older bundle directories may be retained for diagnosis. Stop the backend before manually
removing unused bundles on Windows, because vectors are memory mapped.

## Run

Terminal 1, repository root:

```powershell
.venv/Scripts/python.exe manage.py runserver 127.0.0.1:8000 --noreload
```

Terminal 2:

```powershell
cd frontend
npm ci
npm run dev -- --port 5173 --strictPort
```

Open http://127.0.0.1:5173. Vite proxies `/api` to Django on port 8000, so browser
credentials and cross-origin configuration are unnecessary. Both services bind to
localhost. These are local development servers; public deployment is outside v1.
`npm run build` checks TypeScript and creates the production bundle;
`npm run preview` previews that bundle with the same API proxy.

## Steam API key

Browsing the prepared demo never requires a key. Offline collection operations that
use authenticated Steam endpoints require the operator's own `STEAM_API_KEY`.
Configure it in the process environment or copy `.env.example` to `.env` and fill
it locally. Existing `1_Coleta_Dados/.env` configuration is also supported by the collector.
Environment variables take precedence, then root `.env`, then the collection `.env`.
Register a key at https://steamcommunity.com/dev/apikey. Never put it in `VITE_*`
variables or browser storage. No key entry form or credential API exists.

The catalog collection notebook checks for the key before listing games. Its shared
HTTP helper strips request URLs from raised network/HTTP errors, which could otherwise
contain query-string credentials. Do not enable third-party HTTP debug logging when
running authenticated collection. No network collection is part of web preparation.

Before future collection runs, verify endpoints and access requirements against
https://partner.steamgames.com/doc/webapi/IUserReviewsService and the relevant endpoint's
documentation. A regular key does not guarantee access to publisher-only operations.
The historical collection notebooks are preserved; this change does not migrate their
review endpoints or claim those legacy endpoints still work.

Optional backend variables: `DJANGO_SECRET_KEY`, `DISCOVERY_DATABASE`, and
`DISCOVERY_ARTIFACTS`. The local-only fallback secret is not intended for hosting.

## API contract

All endpoints use JSON and are anonymous/read-only. Only GET is accepted.

- `GET /api/v1/search/?q=...&limit=10`: `query`, `results`, `known_terms`,
  `unknown_terms`, `message`. Each result contains `rank`, `similarity`, and the
  game fields below. Query is trimmed, required, and limited to 500 characters;
  limit is an integer from 1 to 50. An unknown-vocabulary query returns 200 with
  no results and a helpful message. Similarity is cosine similarity, not a probability.
- `GET /api/v1/games/{appid}/`: `appid`, `name`, `description`, `genres` and
  `user_tags` (string arrays), `steam_url`, `review_count`, `recommended_count`.
  These counts cover collected English reviews only. No price/image fields are invented.
- `GET /api/v1/games/{appid}/insights/`: `appid`, `analysis_version`, `status`,
  `collected_review_count`, `analyzed_review_count`, `positive`, `negative`, `note`.
  Each point has `aspect`, `support_count`, and `evidence` containing `review_id`
  and an original `excerpt`. Status is `ready`, `not_prepared`, `no_reviews`, or
  `insufficient_evidence`. Missing insights return 200 with empty arrays.
- `GET /api/v1/health/`: `database`, `catalog`, `reviews`, `search`,
  `insights_prepared_games`, `detail`. Missing database tables return 503 with a
  migration instruction; unready catalog/search returns 503. Review preparation
  progress is informational and does not prevent searching.

Invalid query inputs return 400 with field-to-error-array JSON. Unknown games return
404 with `detail`. Unavailable/incompatible search artifacts return 503 with `detail`
and preparation instructions. Response interfaces live in `frontend/src/api.ts`.

## Interpretation and quality checks

The extractor considers explicit aspect words, splits sentence/contrast/conjunction
clauses, and parses relevant clauses only. It requires a nearby opinion in the
dependency tree, abstains on unresolved multiple aspects, hypotheticals, comparisons, or competing sentiment,
and uses VADER compound thresholds ±0.05. This prioritizes precision over coverage;
sarcasm, implied aspects, and context across clauses remain limitations.

Each side shows at most five aspects, ranked by distinct supporting reviews, with
at least two supporting reviews per aspect/polarity and up to three excerpts. One
review may support both polarities, but repeated mentions do not inflate a count.
Steam recommendation votes are stored separately from aspect sentiment.

```powershell
.venv/Scripts/python.exe manage.py test discovery_api
.venv/Scripts/python.exe -m unittest discover -s 1_Coleta_Dados -p test_steam_scraper.py
.venv/Scripts/python.exe manage.py benchmark_demo
.venv/Scripts/python.exe manage.py audit_insights
cd frontend
npm test
npm run build
```

For a reproducible manual quality review, `evaluate_insights --export PATH` samples
50 candidate clauses (seed 42), ten from each of the first five games with enough
aspect-bearing clauses. Fill each `expected` with `{aspect, polarity}` records or
`[]` for ambiguous/neutral text, then run `evaluate_insights --annotations PATH`.
This reports precision among emitted clause observations, coverage, recall, and
false positives. It is a small development evaluation, not a Steam-wide accuracy claim.
The acceptance target is at least 80% precision; tighten ambiguous extraction rules
and rerun preparation if the target is missed.

`audit_insights` verifies every saved excerpt belongs to its game and is a verbatim
substring of the source review. It also checks full preparation coverage, point
limits, and supporting counts; run it after full insight preparation finishes.
