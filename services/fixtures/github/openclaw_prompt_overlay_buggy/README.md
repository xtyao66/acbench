## OpenClaw Prompt Overlay Buggy Fixture

Localized reproduction of OpenClaw issue `#63076`.

This fixture models a provider-specific GPT-5 prompt overlay bug where
aggregator providers such as OpenRouter and OpenCode do not receive the GPT-5
overlay even though the model family is still GPT-5.
