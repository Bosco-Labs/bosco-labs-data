# Benchmark 2: replicate journals

Each replicate writes every model call to a journal (`runs.jsonl`). Its line count and hash are
published as soon as the replicate ends, so the journal cannot change before the results come out.
The full journal holds the model's text and is not published; `../results/runs_public.jsonl` has
the same attempt lines without it, so the counts can be checked but the journal hash cannot.

| Replicate | Finished (UTC) | Attempt lines | Journal SHA-256 |
|---|---|---|---|
| 1 | 2026-11-20 16:10 | 310 | `0ce31afa15998c0a0461d4411d6bf00e13356791f042be4af530fc088f097f7a` |
| 2 | 2026-11-22 21:15 | 515 (both replicates; the journal is shared) | `3c08bd2c7ddb94786b7d2611460845cd3ca8dd4491d3311970bcf4660061dc3a` |
