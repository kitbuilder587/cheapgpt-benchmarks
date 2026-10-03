# Leaderboard

`leaderboard/index.json` is the normalized public data source for the website. It contains only
results that passed their official, community or partner verification flow and have a compatible
independent reference.

A row is eligible only when model, reasoning effort, dataset release, subset, prompt and scoring
contract match its reference. The schema requires both the primary reference URL and a durable
public snapshot, plus the immutable run artifact URL. An incompatible research run stays outside
this index even when its score looks favorable.

The first provider set is CheapGPT, Ромарио, «Польза» and GPTunnel. Partner runs use dedicated test
balances and the same runner/configuration as CheapGPT. Provider credentials, billing metadata and
private route identifiers are never published.

The website filters individual rows by model, benchmark, provider, reasoning effort and run type.
It does not calculate a composite score across incompatible benchmark methodologies.
