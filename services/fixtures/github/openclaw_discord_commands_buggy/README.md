## OpenClaw Discord Commands Buggy Fixture

Localized reproduction of OpenClaw issue `#53416`.

This fixture models the Carbon reconcile regression where native slash
interactions are incorrectly routed through the plugin-command path and end up
returning a bare `Done.` instead of the command response.
