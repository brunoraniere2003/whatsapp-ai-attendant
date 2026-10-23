# Webhook rejected

## Symptom

Meta's webhook setup says the callback could not be verified, or events stop arriving and Meta shows failed deliveries.

## Detection

`invalid_signatures` grows in `/metrics`; the log has `signature.invalid` events; verification requests answer 403.

## Diagnosis

1. 403 on `GET /webhook`: `WA_VERIFY_TOKEN` is missing or differs from the token typed in the Meta app. The service fails closed when the variable is empty.
2. 401 on `POST /webhook`: `WA_APP_SECRET` is not the app secret of the same Meta app, or a proxy changed the body before it reached the service (the HMAC covers the raw bytes).
3. A burst of 401 from unknown sources is someone probing the endpoint; it is harmless, the events are not processed.

## Mitigation

Set the right variables and restart. Never disable the signature check in production to make the error go away.

## Fix

Store the verify token and the app secret in the secret manager, and keep proxies from re-encoding JSON bodies.

## Prevention

Alert when `invalid_signatures` grows by more than 20 in 5 minutes; keep the secrets out of the config file (enforced by a test).

## Owner

Service operator.
