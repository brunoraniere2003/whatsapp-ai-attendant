# ADR-006: Webhook processing: fail closed, off the event loop, marked after success

Status: accepted
Date: 2026-10-23

## Context

The review of piece 1 found that `POST /webhook` was an `async` function that called the synchronous engine directly, so a slow classification (the optional LLM call had a 10 second timeout and 2 retries) froze every other request of the process, `/health` and `/metrics` included. The attendant held one process-wide lock around the classification. The message id was recorded as processed before the message was handled, so an exception lost the message for good. Without `WA_APP_SECRET` the webhook accepted unsigned events, and the body was read whole, with no size limit, before the signature check.

Meta delivers webhook events at least once: an event that does not get a 2xx answer is delivered again, with backoff, for some days.

## Decision

- Fail closed. Without an app secret the webhook answers 503 to every event; `whatsapp.allow_unsigned = true` is the only way to accept unsigned events, for local tests. The service refuses to start when it can send messages (`WA_ACCESS_TOKEN`) but cannot verify them (no `WA_APP_SECRET`). `/health` reports `signature_check`, so a deployment without the secret is visibly unhealthy.
- Bound the input before any work. A declared Content-Length above `whatsapp.max_body_bytes` (1 MiB) gets 413 at once; a body without Content-Length is read in chunks and abandoned with 413 as soon as it passes the limit. Only then is the HMAC checked.
- Handle messages in a worker thread (`run_in_threadpool`) before answering. The event loop stays free, and the answer still reflects whether handling worked. The attendant serializes the messages of one phone with a lock kept in the session; different phones never wait for each other.
- Keep the inline LLM budget short: 3 second timeout and 1 retry by default, at most 5 seconds and 1 retry by configuration, so the worst case for one message stays well inside Meta's patience.
- Mark a message id as processed only after it was handled. Each message of a payload has its own `try`: a failure is logged as `message.failed` with the traceback, the id goes back to "not processed", the other messages are still handled, and the event gets 500 so Meta redelivers it. On redelivery the messages already handled are skipped as duplicates and only the failed one runs again. After `whatsapp.max_processing_attempts` (3) failures the message is dead-lettered: marked, counted in `dead_letters`, logged, and the event answered 200, so a message that always fails cannot keep the event alive forever.
- A message id in flight counts as a duplicate, so a redelivery that arrives while the first copy is still being handled does not run it twice.
- The raw message id never reaches the log: a Cloud API `wamid` is the base64 of a record that contains the sender's phone. Logs carry `message_ref`, an HMAC of the id with a key drawn at startup; it correlates the lines of one process and means nothing outside it.

## Consequences

- Replies are still sent after the answer, in the background, as before; a send failure is counted and logged but does not make Meta redeliver the event (the reply would otherwise be computed twice).
- A failure after the dialogue state changed (for example, the order number was stored before the order backend raised) keeps that change when the message runs again. With in-memory state this is acceptable; a persistent store would wrap one message in one transaction.
- The idempotency ledger lives in memory (ADR-003): a restart forgets it, and several replicas would need Redis (`SET NX` with a state field) behind the same three operations: claim, complete and fail.
- A payload with many slow messages is handled one message after the other inside one request. Meta sends one message per event in practice; batching would move handling to a queue, which this version does not need.
