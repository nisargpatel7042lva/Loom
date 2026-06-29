# Loom

Memory-augmented market intelligence agent built with [Cognee](https://github.com/topoteretes/cognee).

> Stub — full docs coming after the hackathon build sprint.

## Quick start

```bash
uv venv && source .venv/bin/activate
uv pip install "cognee[all]"
cp .env .env.local   # fill in your API keys
python tests/test_cognee_smoke.py
```

## Structure

| Directory | Purpose |
|-----------|---------|
| `ingest/` | `remember()` pipeline — ingests raw market data into Cognee |
| `memory/` | `recall()`, `improve()`, `forget()` wrappers |
| `agent/`  | Reasoning loop |
| `data/`   | Raw market data fixtures for local dev |
| `demo/`   | CLI / web demo |
| `tests/`  | Smoke tests and integration tests |
