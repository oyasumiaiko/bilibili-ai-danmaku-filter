# Contributing

Contributions that improve real-world filtering accuracy, documentation,
browser compatibility, or test coverage are welcome.

1. Open an issue describing the issue, with a reproducible case where possible.
2. Work on a feature branch; keep changes scoped and reviewable.
3. Run the offline tests and syntax checks locally before submitting a pull request.
4. For browser changes, include an isolated Playwright regression test or a
   description of how to reproduce in a non-personal browser profile.
5. Keep changes local-first; do not introduce remote AI inference or new data
   collection without explaining it and making it opt-in.

## Privacy and safe contributions

Never commit generated userscripts, local_auth.json, downloaded weights, HAR
capture, cookies, authenticated headers, raw account data, or bulk scraped comments.
Only include invented or suitably anonymized example danmaku in public issues.

## Running tests

```bash
python -m pip install "numpy>=2.0,<3"
python -m unittest discover -s tests -p "test_release_*.py" -v
node --check browser_filter/bilibili_ai_filter.template.user.js
node --check browser_filter/diagnostics_module.js
```

The optional Playwright integration tests require the model and local backend
to be running, plus a Chrome/Chromium installation. They are not part of
the lightweight CI, which deliberately avoids model downloads and external APIs.

The bundled 687-item development benchmark has known train/tuning leakage; do
not present its in-sample metrics as independently validated model accuracy.
