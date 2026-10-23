# Webhook rejected

## Symptom

Meta's webhook setup says the callback could not be verified, or events stop arriving and Meta shows failed deliveries.

## Detection

`invalid_signatures` or `oversized_bodies` grows in `/metrics`; `/health` answers 503 with `signature_check: false`; the log has `signature.invalid`, `signature.unconfigured` or `body.too_large` events; verification requests answer 403 or 400.

## Diagnosis

1. 403 on `GET /webhook`: `WA_VERIFY_TOKEN` is missing or differs from the token typed in the Meta app. The service fails closed when the variable is empty.
2. 400 on `GET /webhook`: `hub.challenge` is not 1 to 64 digits. Meta always sends digits; anything else is not Meta.
3. 503 on `POST /webhook` and `signature_check: false` in `/health`: `WA_APP_SECRET` is not set. The webhook refuses every event rather than accept unsigned ones (ADR-006). The service refuses to start at all when `WA_ACCESS_TOKEN` is set without `WA_APP_SECRET`.
4. 401 on `POST /webhook`: `WA_APP_SECRET` is not the app secret of the same Meta app, or a proxy changed the body before it reached the service (the HMAC covers the raw bytes).
5. 413 on `POST /webhook`: the body passed `whatsapp.max_body_bytes` (1 MiB). Meta's events are a few kilobytes, so this is almost always a probe; raise the limit only if real events are being cut.
6. A burst of 401 or 413 from unknown sources is someone probing the endpoint; it is harmless, the events are not processed.

## Mitigation

Set the right variables and restart. Never set `whatsapp.allow_unsigned = true` in production to make the error go away: it exists for local tests only.

## Fix

Store the verify token and the app secret in the secret manager, and keep proxies from re-encoding JSON bodies.

## Prevention

Alert when `invalid_signatures` grows by more than 20 in 5 minutes and whenever `/health` reports `signature_check: false`; keep the secrets out of the config file (enforced by a test).

## Owner

Service operator.
