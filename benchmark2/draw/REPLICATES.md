# Benchmark 2: replicate journals

Each replicate writes every model call to a journal (`runs.jsonl`). Its hash is published as
soon as the replicate ends, so the journal cannot change before the results come out; the
journals are published with the results.

| Replicate | Finished (UTC) | Attempt lines | Journal SHA-256 |
|---|---|---|---|
| 1 | 2026-11-20 16:10 | 310 | `0ce31afa15998c0a0461d4411d6bf00e13356791f042be4af530fc088f097f7a` |