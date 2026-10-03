# Security and privacy

Official runs use a dedicated eval-only API key. Sanitization happens before artifact persistence.
CI blocks publication when secret scanning, schema validation, checksum validation or attempt
completeness checks fail.

The publication set excludes authorization, API keys, cookies, personal data, internal account or
route identifiers, provider-issued response, request, safety and prompt-cache identifiers,
encrypted reasoning payloads, private infrastructure URLs and unrelated user traffic. The API may return a
reasoning summary; it is retained when available. Hidden chain-of-thought is never requested,
reconstructed or claimed.

LiveCodeBench executes untrusted generated code only inside its pinned Docker environment. Do not
run the code harness directly on a workstation or CI host.

