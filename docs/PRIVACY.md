# Privacy and storage

**Data stays local for classification.** The script obtains the current
video's public danmaku data from Bilibili's own APIs and sends the needed text
to a Python service on the same host via 127.0.0.1. It does not make requests
to a third-party AI classification provider.

What is stored locally:

- `browser_filter/state/local_auth.json`: randomly generated API secret.
- `browser_filter/state/backend_settings.json`: backend settings.
- Tampermonkey's private script preferences: category choices, phrase rules,
  and cache/timeout settings.
- In-memory model-result caches and bounded per-video diagnostic history.
- Local log files and downloaded model artifacts, excluded from Git.

What is **not** bundled with this repository: your browser profile,
authentication cookies, private Token, generated userscripts, raw scraped
danmaku datasets, model binaries, historical experiment records and
personalized filtering decisions.

The diagnostics JSON export is created only after the user explicitly clicks
Export. It contains text of the observed public comments and model decisions
from the current page. Treat exported data as you would any other local
download; review it before sharing.

The current JavaScript implementation supports only a subset of Bilibili's
DOM-based text comments and is not intended as a full-network crawler.
