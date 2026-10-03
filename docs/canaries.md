# Rotating canary protocol

Private canaries detect benchmark-specific routing and memorization without weakening public
reproducibility of the five main suites. They are reported separately under Integrity and never
enter the five public scores.

The active prompts and reference answers live in a separate private repository encrypted with
SOPS; the age private key stays outside GitHub. Before evaluation, maintainers publish a versioned
commitment hash. While the set is active, only aggregates, versions and hashes are public.

At the next official release, maintainers disclose the previous prompts, reference answers and
responses in full. Anyone can then recompute the commitment and aggregate. A new committed set is
active before the old one is disclosed.

