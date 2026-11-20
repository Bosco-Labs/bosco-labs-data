# Benchmark 2: the draw

The companies of Bosco Labs' second counterparty-check benchmark were drawn on
2026-11-20 at 15:10 UTC, after drand "quicknet" round 34127812 (2026-11-20T15:00:00Z), with the
frozen plan in `../prereg/` (bundle hash
`8e07275e0d1a289e69624bea86e34653f23640fb7369efa1491563a91d193c68`).

- Set hash: `b38d0175742210c29509ac71e837c94b4a9ed54c77d517091f2d0db20a95fb3f`
  (SHA-256 of `data/benchmark2/set.json`, CRLF read as LF, as `tools/bench2_lib.py` `sha256_norm`
  computes it)
- 102 companies from Estonia, Ireland, Latvia and the United Kingdom, every quota filled, no
  shortfalls.
- Hand check (protocol step 8): all 24 audit rows agree with the official register pages.

The list itself stays private until the results are published, so the runs cannot be tuned to
it; it is published with the results, and anyone can then check it against this hash and redo
the draw from the bundle and the drand round.