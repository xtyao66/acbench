## OpenClaw Memory Status Buggy Fixture

Localized reproduction of OpenClaw issue `#62855`.

This fixture models the `status --deep` path that loses config context while
resolving fallback embedding providers and also renders missing counts as
visible `None` values.
