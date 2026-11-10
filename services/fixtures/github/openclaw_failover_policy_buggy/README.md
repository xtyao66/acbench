## OpenClaw Failover Policy Buggy Fixture

Localized reproduction of OpenClaw issue `#62848`.

This fixture models a main-lane failover policy that waits one transport error
too long before falling back, causing avoidable user-visible degradation.
