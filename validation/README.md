# Development validation

`insight_annotations.json` contains 50 original review clauses, ten each from five
games, sampled with seed 42 before inspecting model predictions. `expected` labels
were assigned by Codex through manual reading, including abstentions for neutral,
ambiguous, and other-title statements. They are **not independent human annotations**.
The corpus includes FPS genre references and comparisons to other games. The saved
sample used the v2 lexical gate (which still included FPS); exporting a new sample
with the tightened v3 vocabulary can select different clauses.

The initial broad dependency-radius extractor emitted 15 points, 8 correct
(53.3% precision). Errors included genre/acronym ambiguity, misplaced sentiment,
and praise about a different title. The final extractor uses explicit grammatical
opinion links and abstains on comparisons/hypotheticals. The same development sample
now produces 5 correct points, no false positives, 10% clause coverage, and 18.5%
point recall. This meets the 80% development precision target but has low recall.
These clauses were used to improve the rules; the results are not a held-out
estimate or evidence that deployment accuracy is 100%. A separate human-labeled
set is needed before making broader accuracy claims.

Reproduce with:

```powershell
.venv/Scripts/python.exe manage.py evaluate_insights --annotations validation/insight_annotations.json --output validation/insight_metrics.json
.venv/Scripts/python.exe manage.py benchmark_demo
```

`benchmark.json` records this machine's measured HTTP-handler latency (Django test
client), process resident memory, artifact size, and dataset counts. The test forbids
network connections and clears `STEAM_API_KEY`. This excludes browser/network latency
and is a single-process local benchmark. The original Word2Vec settings trained on
179,464 descriptions in 345.4 seconds. A changed corpus or interpreter hash seed can
change newly trained vectors; parity checks compare the same trained model.

Backend tests compare exported-index scores and ranking with the notebook's original
scikit-learn cosine calculation, exercise invalid/missing inputs and corrupt artifacts,
verify review evidence ownership, and test repeatable offline imports. The frontend
interaction test covers search → details → expanded evidence with mocked API responses;
live browser checks separately exercise the real local API.

The completed preparation contains 179,464 games, 395,256 English reviews, and
29,625 current-version game insight records. The final resumed insight pass processed
the remaining 26,930 games in 1,352.4 seconds; 2,695 had already been prepared.
This is resumed-run timing, not an uninterrupted end-to-end measurement.

The full evidence audit checked 28,686 saved excerpts with no ownership or verbatim-text
errors, and confirmed that every imported review was analyzed. The final benchmark
measured 85.1 ms median / 92.5 ms maximum warm search-handler latency, 1.6844 seconds
for the cold handler, 348.3 MB process RSS, and 206.8 MB of active search artifacts.
See the saved JSON reports for the exact measurements and query.

Validation passed 15 backend tests, 13 collection/scraper tests, four frontend
interaction tests, the TypeScript/production build, Django checks and migration
consistency, and Python dependency consistency. Desktop and 390-pixel mobile
screenshots are saved alongside the reports; the mobile page had no horizontal overflow.
