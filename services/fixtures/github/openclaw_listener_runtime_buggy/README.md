## OpenClaw Listener Runtime Buggy Fixture

Localized reproduction of OpenClaw issue `#62840`.

This fixture models a listener path that throws when an event arrives after an
agent run has already ended, causing the gateway to crash instead of skipping
the event safely.
