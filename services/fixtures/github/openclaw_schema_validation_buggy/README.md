## OpenClaw Schema Validation Buggy Fixture

Localized reproduction of OpenClaw issue `#62856`.

This fixture models a plugin-schema traversal path that recurses forever when
`$ref` definitions point to each other.
