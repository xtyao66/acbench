# openclaw_completion_runtime_buggy

Localized ACBench reproduction of `openclaw/openclaw` issue `#10864`.

Seeded defect:

- finished completion worker records are not cleaned up when a session ends

This fixture models the leak path behind orphan completion processes and memory pressure.
