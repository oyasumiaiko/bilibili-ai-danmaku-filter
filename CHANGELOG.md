# Changelog

## v1.3.0 — Sidebar diagnostics

- Nonintrusive diagnostics entry in Bilibili's native right-side danmaku header.
- Separate lists for actually rendered comments and distinct lookahead comments.
- Filter by decision and category, search text, and export bounded JSON history.
- Preserve live-priority classification and fallback visibility on backend errors.
- Keep the settings panel behind an explicit Tampermonkey menu action.

## v1.2.0 — Immediate display

- Unclassified comments remain visible rather than waiting for CPU inference.
- Foreground comment classification takes precedence over prefetch.
- Background prefetch batches are bounded to reduce interference with live viewing.
- Video seeking discards obsolete pending prefetch queue items.

## v1.1.0 — Settings and local inference

- 19 independently configurable filtering categories.
- Category sensitivity, custom allow/block phrases, live preview and profile presets.
- Dedicated loopback Python backend with authenticated settings and cache API.
- 6-minute-segment danmaku lookahead and local caches.

The published source repository is a cleaned, portable distribution assembled
from the local development project. Earlier experiments and raw datasets are
not part of this distribution.
