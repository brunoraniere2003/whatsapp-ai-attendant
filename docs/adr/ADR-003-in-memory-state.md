# ADR-003: In-memory state behind small interfaces

Status: accepted
Date: 2026-10-22

## Context

The service keeps three kinds of state: a session per phone (pending question, collected order number, failed turns, handoff), the ids of processed messages (idempotency) and the learning queue. A demo and a single small store do not justify a database, but the code must not paint production into a corner.

## Decision

- Sessions and processed ids live in `TTLStore`, a thread-safe least-recently-used map with a TTL and a size cap (`dialogue.session_ttl_seconds`, `dialogue.max_sessions`, `whatsapp.idempotency_ttl_seconds`, `whatsapp.idempotency_max_ids`).
- The learning queue is a bounded deque (`dialogue.learning_queue_size`).
- The attendant holds one lock per process while it updates a session.
- There is no database, so there are no schema migrations and no backups in this version.

## Consequences

- A restart forgets sessions, processed ids and the learning queue. Meta may then redeliver an event the service already answered, and the customer could get the reply twice.
- More than one replica would not share state.
- Production replaces `TTLStore` with Redis (`SET NX EX` for idempotency, hashes with TTL for sessions) and persists the learning queue. That change adds versioned migrations, backups with retention and an integrity check, as the team standard requires.

## Revisit when

The service runs with more than one replica, or the learning queue must survive restarts.
