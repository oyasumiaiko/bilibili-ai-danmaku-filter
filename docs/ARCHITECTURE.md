# Architecture and decisions

## Modules

- `browser_filter/bilibili_ai_filter.template.user.js`: page observer, native
  danmaku visibility, two-level scheduler, protobuf segment fetch/decode,
  local authenticated calls and preferences.
- `browser_filter/diagnostics_module.js`: bounded per-video observation
  history, sidebar mounting, UI filters and JSON export.
- `browser_filter/build_userscript.py`: builds private local userscript
  with a random local API token; constructs an absolute file:// loader.
- `browser_filter/backend.py`: loopback HTTP, authentication, settings,
  request validation, single warmed shared model and cache reuse.
- `scripts/preferences_realtime_filter.py`: zero-shot classifier, strong
  regexes and exceptions, positive/negative prototype vector scoring.
- `config/filter_categories.json` and `assets/*`: calibration and prototypes.

## On-screen versus prefetch

The observer sees newly attached DOM text nodes or re-used nodes with changed
content, puts each into the priority queue, and **does not hide while pending**.
A prefetched, cached decision can be applied on node arrival. A new decision
hides only entries marked blocked.

Foreground queue work is processed before queued prefetch work. At most one
backend classification batch is in flight from a script instance. Already
running prefetch work cannot be preempted but uses a maximum of 8 texts per
batch to reduce worst-case delay. This is not a frame-level latency guarantee.

Prefetch is based on Bilibili's available 6-minute danmaku protobuf segments
for the video being watched. Only nearby segments are kept in memory, and
seeking/route changes invalidate stale pending prefetch items.

## Local embedding classifier

The application uses EmbeddingGemma 2's text-only backbone; one Document-task
embedding is reused for all eligible categories. Strong patterns and
exceptions can short-circuit inference. For semantic scoring, precomputed
reference vectors are combined with calibrated profile-specific cosine
thresholds, hard-negative comparisons, and per-category offsets. One sentence
may match several categories.

Profile thresholds were tuned using a manually labeled sample reused in
evaluation. The reported development metrics are in-sample and should be
treated as descriptive, not generalization claims.

## Diagnostics semantics

- On-screen observations count DOM instances. Reused nodes with changed text
  create new entries; pending entries made obsolete by reuse are labeled
  unclassified.
- Prefetch entries represent deduplicated comment texts and may contain
  several timestamps. This is intentionally a separate denominator.
- The browser records at most 2,500 screen events and 1,800 distinct prefetch
  texts per video. No database is written.
- On navigation to a new video identity, counters/history reset.
- An offline or unresponsive backend does not prevent comments from appearing.

## Third-party boundaries

The script communicates with Bilibili's own video/segment endpoints and a
loopback local server. No cloud AI service is called. The model is downloaded
separately under its upstream license; no pretrained weights are committed.
