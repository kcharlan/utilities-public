# Compressed rollout fixture

Synthetic data only: session id `00000000-0000-4000-8000-000000000001`, response ids
`resp_synthetic_NN`, working directory `/tmp/com.example.project`. It holds 13 lines and ends
with a newline.

`synthetic_rollout.jsonl.zst` is the compressed form of `synthetic_rollout.jsonl`, made with
zstd 1.5.7:

```sh
zstd -19 -q -f synthetic_rollout.jsonl -o synthetic_rollout.jsonl.zst
```

| File | sha256 |
|---|---|
| `synthetic_rollout.jsonl` | `8483ea69ddaa3255ff9bba83581d7395701ba4e696350ec13e8b339c3812d444` |
| `synthetic_rollout.jsonl.zst` | `5a9d27ad7caecb958bf6fd3d53303fb5239c4ef620581fa266c5c513e177aa89` |

`ZstdReaderTests` builds every other case (multiple frames, exact buffer-sized expansion,
truncation, corruption) from `StoredZstdFrame`, so only this one file comes from the real
compressor.
