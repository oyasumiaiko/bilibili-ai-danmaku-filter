# Decision-model benchmarks: EmbeddingGemma 2 vs Jev-like alternatives

**Chinese full methodology: [BENCHMARKS.md](BENCHMARKS.md)**

**Local evaluations:** 16–17 October 2026, Windows / AMD Ryzen 9 5950X / CPU only. **No GPU results are inferred.**

## What is being measured?

The binary task is to detect *anime-production-related danmaku* in short Chinese comments: drawing quality, animation budgets, CGI/3D, PPT/static scenes, storyboarding and related production meta commentary. Ordinary story/character discussion and unrelated chat are negative.

This is **not** a 19-category evaluation. The current released v1.3 classifier was configured with only its two production-related categories (`budget_meta` and `art_meta`) active. Other nuisance categories were not tested against Jev-like models here.

## Quality: 335 overlapping development examples

The 335 comments comprise 135 positives and 200 negatives (18 ambiguous records excluded from 353 manually reviewed cases).

| Model / policy | TP | FP | FN | TN | Precision | Recall | **F1** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Current v1.3, high_recall, two production categories** | 105 | **4** | 30 | 196 | **96.3%** | 77.8% | **86.1%** |
| Current v1.3, balanced | 105 | 6 | 30 | 194 | 94.6% | 77.8% | 85.4% |
| Earlier specialist EmbeddingGemma + production-specific rules | 117 | 3 | 18 | 197 | 97.5% | 86.7% | 91.8% |
| GLiNER2.5-multi-Decide, Chinese 3-way labels | 76 | 38 | 59 | 162 | 66.7% | 56.3% | 61.0% |
| GLiNER2.5-multi-Decide, detailed English labels | 133 | 195 | 2 | 5 | 40.5% | **98.5%** | 57.5% |

The earlier specialist rules were **not the code currently released in this repository**. Their 91.8% F1 must not be attributed to the current 19-category engine.

## Quality: the same 40 examples, including d3-lite

These 40 cases are a fixed, balanced 20-positive/20-negative subset **of the 335 above**, not an independent holdout.

| Model / policy | TP | FP | FN | TN | Precision | Recall | **F1** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Current v1.3 high_recall (two categories)** | 15 | 1 | 5 | 19 | **93.8%** | 75.0% | **83.3%** |
| d3-lite, OR across 5 independent `noul` questions, p≥0.55 | 19 | 9 | 1 | 11 | 67.9% | **95.0%** | 79.2% |
| d3-lite, post-hoc selection of 4 question heads, p≥0.50 | 19 | 7 | 1 | 13 | 73.1% | 95.0% | 82.6% |
| GLiNER2.5, direct 3-way classification | 9 | 5 | 11 | 15 | 64.3% | 45.0% | 52.9% |
| GLiNER2.5, OR across 7 heads | 7 | 7 | 13 | 13 | 50.0% | 35.0% | 41.2% |
| Earlier specialist EmbeddingGemma rules (not v1.3) | 18 | 0 | 2 | 20 | 100.0% | 90.0% | 94.7% |

The optimized d3 4-head policy **was selected using the evaluation cases themselves**. Do not interpret 82.6% as independent performance. The 83.3% vs 82.6% difference is too small to support a robust model ranking.

## Warm CPU latency: different workloads and thread counts

| Model / configuration | Evaluated work | CPU threads | p50 | p95 |
| --- | --- | ---: | ---: | ---: |
| Current v1.3 full policy calls | 335 comments; only 97 require embedding | 4 | **0.01 ms** | **78.5 ms** |
| EmbeddingGemma 2 historical encode + scoring | 96 distinct comments; every text encoded, batch=1 | 4 | **67.8 ms** | 87.1 ms |
| GLiNER2.5 direct 3-way | 335 comments | 12 | 88.9 ms | 108.6 ms |
| GLiNER2.5 7 heads | 335 comments | 12 | 168.2 ms | 195.4 ms |
| d3-lite one `noul` question | **5 comments only** | 12 | **2,616 ms** | Not reported |
| d3-lite seven `noul` questions | 40 comments | 12 | **12,557 ms** | 13,849 ms |

The v1.3 all-case **0.01 ms median is not model inference latency**. It is the median over a mixed stream of mostly lexical/shortcut decisions; 97/335 comments actually triggered an embedding. For model-only latency, consult the 67.8 ms historical single-encode measurement.

d3-lite's CPU results use a reference PyTorch implementation. Its [official model card](https://huggingface.co/vllm-sr/d3-lite) reports approximately 13.6 ms on an **AMD MI325X GPU**; that GPU number is not comparable with this machine's CPU-only tests. The values above exclude cold start / model loading and were collected in somewhat different runtime conditions.

Model weight **disk file** sizes observed locally: EmbeddingGemma text-only 542 MB, GLiNER2.5 multilingual 1,149 MB, and d3-lite 1,706 MB. Disk sizes are *not* runtime RAM or VRAM measurements.

## Why this design, rather than generic Jev-like models?

- **EmbeddingGemma 2 + deterministic rules (the current architecture):** Useful when the target classes are known, short Chinese comments need context, the model runs on local CPU and many comments can be short-circuited. Its performance on the tested production-related category is competitive and already integrated with Bilibili's lookahead pipeline.
- **[d3-lite](https://huggingface.co/vllm-sr/d3-lite):** A real open decision model exposing `choice`, `noul` and `score`. It achieves higher recall on the 40-case test, but more false positives; the tested CPU reference path is too slow for foreground on-screen filtering. An optimized GPU deployment may change the tradeoff.
- **[GLiNER2.5-multi-Decide](https://huggingface.co/fastino/GLiNER2.5-multi-Decide):** A 287M multilingual direct-label model. Despite promising general-purpose decision capabilities, the tested Chinese topic schemas underperformed this domain-tuned pipeline.
- **[Jevlike](https://github.com/vinnylarouge/jevlike):** A lightweight option-attention starter model. Its default byte encoder requires task-specific training; no matched Bilibili evaluation was run.
- **[JevEmbed](https://github.com/HITsz-TMG/JevEmbed):** Decision heads and task-specific fine-tuned embedding backbones; no matched Bilibili evaluation was run.
- **TypeSafe Jev:** Proprietary hosted decision service; no matched evaluation and it does not meet this project's default offline/local requirement.

The model vendors' public benchmark tables use *different tasks and hardware*. They are not silently mixed with these local Chinese danmaku confusion matrices.

## Caveats and reproducibility

1. **In-sample tuning overlap:** The old specialist pipeline, current 19-category rules, and some competitor prompts were selected with overlapping reviewed comments. These scores are **development-set evidence, not held-out validation**.
2. **Label prevalence and sample bias:** The 40-item subset is artificially balanced. Precision on natural video traffic can vary.
3. **Unequal optimization:** The embedding/rule pipeline has more domain tuning than the initially prompted Jev-like alternatives. A fair general-purpose comparison would equalize development data, tuning budget, model runtimes and separately held-out videos.
4. **Runtime mismatch:** Thread count, per-call question count, latency definitions and sample sets differ. These are engineering indicators, not rigorous speed leaderboard data.
5. **Limited scope:** No full 19-category head-to-head, no authenticated Jev service run and no Jevlike/JevEmbed local quality number.

The repository distributes **aggregate results without raw comments, case IDs or private annotations**:

- [Sanitized benchmark data](../benchmarks/decision_models_2026-10-16.json)
- [Paired JSONL scoring tool](../benchmarks/evaluate_jsonl.py)
- [Synthetic scoring fixture](../benchmarks/fixtures/synthetic_demo.jsonl)
- [Offline benchmark arithmetic tests](../tests/test_release_benchmark.py)

Run:

```bash
python benchmarks/evaluate_jsonl.py --input benchmarks/fixtures/synthetic_demo.jsonl
python -m unittest discover -s tests -p "test_release_*.py" -v
```

The synthetic fixture demonstrates the score calculator and **does not reproduce the reported quality results**. Repeating the original 335/40-item benchmark requires authorized access to the manually labeled corpus, which is not redistributed. You can, however, repeat the same procedure on your own data with model predictions under a shared stable case ID.

**Takeaway:** Under this project's constraints—CPU-only, local processing, known nuisance categories, minimized erroneous hiding—embedding + calibrated rules + prefetch is a reasonable, empirically tested engineering choice. It has not been demonstrated to be globally superior to all Jev-like models.
