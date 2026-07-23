# Atlas Performance & Load Benchmark

Generated 2026-07-23 11:26 UTC.

## Real-repo leg (network clone included)

| Repo | Total (s) | Peak RSS (MB) | Notes |
|---|---:|---:|---|
| https://github.com/octocat/Hello-World | 5.41 | 43.8 |  |
| https://github.com/tiangolo/typer | 7.42 | 53.5 |  |

## Synthetic LOC-scaling leg (no network, isolates compute time)

| Size | Parse+Graph+Quality+Security (s) | Git History (s) | Doc Gen (s) | Total (s) | Peak RSS (MB) | Notes |
|---|---:|---:|---:|---:|---:|---|
| 10,000 LOC (synthetic) | 0.53 | 0.03 | 0.00 | 0.56 | 53.6 |  |
| 25,000 LOC (synthetic) | 1.36 | 0.06 | 0.02 | 1.44 | 53.5 |  |
| 50,000 LOC (synthetic) | 2.64 | 0.11 | 0.03 | 2.78 | 53.2 |  |
| 100,000 LOC (synthetic) | 5.49 | 0.17 | 0.08 | 5.74 | 54.0 |  |
| 250,000 LOC (synthetic) | 13.06 | 0.11 | 0.17 | 13.34 | 65.8 |  |
