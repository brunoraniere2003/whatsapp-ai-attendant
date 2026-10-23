# Service unhealthy

## Symptom

The process exits at startup, or `GET /health` answers 503, or Meta reports that the callback URL does not answer.

## Detection

`python -m whatsapp_attendant health --url https://HOST` exits 1 (run it from the uptime monitor every minute). The log file has no `message.received` lines while traffic is expected.

## Diagnosis

1. Read the startup error: `ConfigError` and `KnowledgeBaseError` name the key or the intent at fault.
2. `python -m whatsapp_attendant check-config config.toml` validates the file and its knowledge base.
3. `python -m whatsapp_attendant health --config config.toml` runs the classifier self-test without the server.
4. `classifier_self_test: false` means the knowledge base no longer recognizes "bom dia" as a greeting: an edit removed or broke the greeting examples.

## Mitigation

Roll back to the last configuration and knowledge base that passed `check-config` (both are versioned files), then restart.

## Fix

Correct the key or the intent named in the error, run `check-config`, the tests and the evidence command, and deploy again.

## Prevention

Knowledge base edits go through a pull request; CI runs the tests, `check-config` and the evidence check before merge.

## Owner

Service operator (see the RACI in operations.md).
