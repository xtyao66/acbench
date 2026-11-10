# openclaw_pairing_state_buggy

Localized ACBench reproduction of `openclaw/openclaw` issue `#63035`.

Seeded defect:

- array-typed pairing state files are not coerced back to mappings before request approval

This fixture keeps the reproduction small while preserving the core failure chain from
the GitHub issue.
