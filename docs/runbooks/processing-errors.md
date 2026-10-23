# Processing errors

## Symptom

Meta shows failed deliveries (HTTP 500) for the webhook, or some customers get no answer while others do.

## Detection

`processing_errors` grows in `/metrics`; the log has `message.failed` events with `dead_letter` and a traceback in `exc`. `dead_letters` counts the messages the service gave up on.

## Diagnosis

1. Group the `message.failed` lines by the last line of `exc`: one exception type at a high rate is a bug or a broken dependency, a scattered few are transient.
2. A failure in the order backend (in production, the store's ERP) is the usual transient cause: the event got 500, Meta redelivers it, and the next attempt usually works. `message_ref` links the attempts of one message inside one process.
3. `dead_letter: true` means the same message failed `whatsapp.max_processing_attempts` times (3): the event was answered 200 so Meta stops retrying, and that customer got no reply.
4. A failure right after a knowledge base or code release points at the release.

## Mitigation

For a broken release, roll back. For an unavailable dependency, nothing is lost while attempts remain: Meta keeps redelivering. Ask the human agents to contact the customers of dead-lettered messages (the masked phone is in the log line).

## Fix

Fix the cause shown in the traceback and add a regression test with the failing message shape. Handling is marked done only after success (ADR-006), so a fixed bug needs no replay for messages that still had attempts left.

## Prevention

Alert when `dead_letters` grows at all and when `processing_errors` passes 1% of `received` in 15 minutes. Contract tests for the order backend before connecting a real ERP.

## Owner

Developer, with the service operator for the alert.
