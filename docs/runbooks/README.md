# Runbooks

One file per known incident. Every runbook has the same sections: Symptom, Detection, Diagnosis, Mitigation, Fix, Prevention and Owner (a test checks them). Service levels and roles are in [operations.md](../operations.md).

| Runbook | When to open it |
|---|---|
| [service-unhealthy.md](service-unhealthy.md) | the service does not start, or `/health` answers 503 |
| [webhook-rejected.md](webhook-rejected.md) | Meta cannot verify the webhook, or events get 401 |
| [send-failures.md](send-failures.md) | `send_failures` grows or customers get no reply |
| [misunderstood-spike.md](misunderstood-spike.md) | `not_understood` or handoffs after failures grow faster than traffic |
