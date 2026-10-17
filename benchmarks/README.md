# Benchmark data and verification

**[中文 Benchmark 报告](../docs/BENCHMARKS.md) | [English benchmark report](../docs/BENCHMARKS.en.md)**

The source dataset and detailed per-comment predictions are **not** bundled:
they came from manually reviewed third-party Bilibili danmaku used during
development. Do not mistake the aggregate snapshots for a new held-out dataset.

The benchmark snapshot [`decision_models_2026-10-16.json`](decision_models_2026-10-16.json)
contains only confusion matrices, test conditions, CPU latency aggregates,
model weight file sizes, and explicit limitations. It compares:

- The **currently published v1.3 19-class filter**, with only its two
  production-related categories enabled for this specialized binary test.
- An **earlier specialist EmbeddingGemma production-topic rule set**, clearly
  labeled as a different implementation.
- **GLiNER2.5-multi-Decide** on 335 comments and the paired 40-case subset.
- **d3-lite** on the shared 40-case subset with fixed OR rules, plus separately
  labeled post-hoc optimization.

All measured results use an overlapping development/tuning dataset.

## Validate the results in CI

```bash
python -m unittest discover -s tests -p "test_release_*.py" -v
```

The arithmetic validation checks TP+FP+FN+TN, positive/negative denominators,
precision, recall and F1 for every result against the JSON snapshot.

## Compare on a dataset you are allowed to use

This repository includes a **model-agnostic paired evaluator**. It does
not generate model predictions; obtain those with the model's actual inference
runtime and aligned question/label definitions. Sample JSONL row:

```json
{"id":"example-1","gold":true,"predictions":{"embedding":true,"d3":false},"latency_ms":{"embedding":67.1,"d3":2600}}
```

Use exactly the same set of unique IDs and gold labels for each model. Missing
predictions cause an error rather than silently shrinking one model's sample:

```bash
python benchmarks/evaluate_jsonl.py --input benchmarks/fixtures/synthetic_demo.jsonl
python benchmarks/evaluate_jsonl.py --input my_private_predictions.jsonl --output my_private_scores.json
```

The synthetic fixture tests the calculator and **does not provide evidence for
real-world model accuracy**. The tool can reproduce quality statistics from
a suitably licensed full dataset, but the original 335/40-item results cannot
be independently recomputed from this repository alone.

A stronger future evaluation should hold out complete videos/genres not seen
during any rule tuning, match optimization effort for all candidate models,
use the same CPU/GPU environments when measuring latency, and report false
positive counts alongside recall.
