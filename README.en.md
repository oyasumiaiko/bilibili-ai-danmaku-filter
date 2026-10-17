# Bilibili AI Danmaku Filter

[简体中文](README.md) | **English**

A local-first semantic danmaku filter for Bilibili, using the **270M-parameter text backbone of Google EmbeddingGemma 2** and a set of 19 independently configurable nuisance categories. It runs on a local CPU and does not require a paid AI API.

![Mocked integration-test screenshot of the sidebar diagnostics UI](docs/media/diagnostics-demo.png)

*Screenshot taken from a synthetic test page, not a logged-in user's account.*

## Highlights

- **Non-blocking playback:** Danmaku are visible immediately. Entries classified as unwanted are hidden after inference; previously prefetched decisions can be applied before the entry appears.
- **Lookahead:** Prefetch and classify near-future danmaku from the current video's official 6-minute protobuf segments (22 seconds ahead by default).
- **Live-priority scheduling:** On-screen entries take priority over background prefetch work.
- **19 configurable categories:** Spoilers, meta-production commentary, engagement directives, moralizing, spam, and more. Category toggles, sensitivity offsets, and manual allow/block phrases.
- **Diagnostics without video overlays:** A small “AI诊断” button sits inside Bilibili's right-side danmaku list header. It opens a categorized, searchable table of actual on-screen decisions versus distinct prefetched texts; supports JSON export.
- **Local service:** A loopback-only Python HTTP server with a per-install token. Inference happens on the same computer.
- **Fail-open playback:** If the backend is unavailable, the original danmaku stays visible rather than delaying normal display.

Supported primarily on desktop Bilibili videos with the current DOM-based text renderer. Special-effect/BAS/image danmaku and later site changes may not be covered.

## Quick start

Requires Python 3.12/3.13, Google Chrome, Tampermonkey, and Git. Downloading the upstream model requires several GB of temporary space; the extracted full-precision text weights occupy approximately 542 MB.

**Windows (PowerShell):**

```powershell
git clone https://github.com/oyasumiaiko/bilibili-ai-danmaku-filter.git
cd bilibili-ai-danmaku-filter
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\download_model.py
.\.venv\Scripts\python.exe scripts\extract_text_only.py
.\.venv\Scripts\python.exe browser_filter\build_userscript.py
.\.venv\Scripts\python.exe browser_filter\backend.py
```

**Linux/macOS:**

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python scripts/download_model.py
python scripts/extract_text_only.py
python browser_filter/build_userscript.py
python browser_filter/backend.py
```

The model source is [google/embeddinggemma-2](https://huggingface.co/google/embeddinggemma-2). The download/extraction step creates an optional **text-only** checkpoint in `models/embeddinggemma-2-text`. You may instead point `AI_DANMAKU_MODEL_DIR` at an existing compatible checkpoint. We **do not ship or commit model weights**.

Import the newly generated `browser_filter/bilibili_ai_filter_loader.user.js` in Tampermonkey and enable file URL access in Chrome. If the default port is occupied, use matching alternate ports with `python browser_filter/build_userscript.py --port 39733` and `python browser_filter/backend.py --port 39733`. Open/refresh a video page; once `http://127.0.0.1:39683/health` reports `status: ready`, filtering is active.

**Do not commit or publish** `browser_filter/state/local_auth.json`, the generated `bilibili_ai_filter.user.js`, or the generated loader. The first contains your authentication token, the second embeds it, and the third includes a device-specific file URL. All three are Git-ignored.

For rule changes, use the Tampermonkey menu command “AI 弹幕过滤：设置”. Diagnostics can be opened from the right-hand danmaku header or the separate Tampermonkey diagnostics menu. No floating button is added over video.

## Design notes

The backend computes a single text embedding per novel eligible comment, scores it against calibrated positive/negative reference vectors, and combines the semantic decisions with hand-written patterns, exceptions, and user allow/block phrases. The repository includes about 1.1 MB of reference vectors and JSON rule definitions. The diagnostic history is memory-only, bounded per open tab, and can be explicitly exported.

The development benchmark involved **687 manually labeled comments also used to tune the rules**. Measured in-sample precision/recall/F1:

| Profile | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| balanced | 90.7% | 93.6% | 92.1% |
| high_recall | 86.5% | 96.2% | 91.1% |
| aggressive | 83.0% | 96.8% | 89.4% |

These figures are **not held-out validation or evidence of real-world accuracy**. There can be false positives and missed targets, especially on unseen video genres.

## Further reading

- [Architecture](docs/ARCHITECTURE.md)
- [Privacy](docs/PRIVACY.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [License](LICENSE) / [Third-party notices](NOTICE)

Project code is MIT licensed. Google EmbeddingGemma 2 is an independent Apache-2.0 licensed model, not included in the repository. Not affiliated with Bilibili or Google.
