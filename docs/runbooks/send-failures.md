# Send failures

## Symptom

Customers write and get no answer, while the webhook answers 200.

## Detection

`send_failures` grows in `/metrics`; the log has `send.failed` events (with `status` and `retryable`) and `send.retry` warnings.

## Diagnosis

1. `status` 401 or 403: the access token expired or lost the `whatsapp_business_messaging` permission. These are never retried.
2. `status` 400: the recipient cannot receive free text (for example, the 24-hour customer service window is closed). A template message is needed.
3. `status` 429 or 5xx, `retryable: true`: Meta is throttling or degraded; the sender already retried with backoff.
4. `status: null`: network errors from the host to graph.facebook.com.

## Mitigation

Renew the token for 401 and 403. For 429 and 5xx, wait; replies inside the attempt budget recover on their own. Tell the human agents to check the conversations that failed.

## Fix

Use a system user token that does not expire; add a template fallback for closed windows; move sends to a durable queue if outages last longer than the retry budget.

## Prevention

Alert on more than 5 `send.failed` in 10 minutes; review `send.retry` weekly.

## Owner

Service operator, with the store's Meta Business administrator for tokens.
