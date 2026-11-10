## OpenClaw MiniMax Usage Buggy Fixture

Localized reproduction of OpenClaw issue `#63056`.

This fixture models a usage-tracker request that calls the MiniMax remains
endpoint with `POST` instead of `GET`.
