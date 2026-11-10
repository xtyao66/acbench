## OpenClaw NO_REPLY Buggy Fixture

Localized reproduction of OpenClaw issue `#63054`.

This fixture models the delivery-layer bug where `NO_REPLY` is only treated as
silent when the model output is an exact match, allowing leaked trailing text to
reach the user instead of being suppressed.
