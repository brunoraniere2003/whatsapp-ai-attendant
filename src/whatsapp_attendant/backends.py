"""Order backend port. The demo ships a deterministic fake; production plugs in the store's ERP."""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Protocol

ORDER_STATUSES = (
    "em separação no estoque, com envio previsto para o próximo dia útil",
    "em transporte, com entrega prevista em até 3 dias úteis",
    "saiu para entrega e chega hoje",
    "entregue, com o recebimento registrado pela transportadora",
)
PAYMENT_STATUSES = (
    "o pagamento já foi confirmado",
    "o pagamento está em compensação",
    "o pagamento ainda não foi identificado",
)


class OrderBackend(Protocol):
    def lookup(self, order_number: str, phone: str) -> dict[str, str] | None:
        """Fields used by the reply templates (order_status and payment_status), or None when the
        order does not exist or does not belong to `phone` (RQ-37)."""
        ...


class FakeOrderBackend:
    """Deterministic fake with per-phone ownership.

    With `owners` (order number to phone), only those orders exist. Without it, every 6-digit
    number is an order, and the first phone that asks about it owns it: any other phone gets None,
    as a real store would answer someone asking about a stranger's order. The status is a pure
    function of the digits. Claims are bounded by `max_orders`, oldest first.
    """

    def __init__(self, owners: Mapping[str, str] | None = None, max_orders: int = 100_000) -> None:
        self._fixed = owners is not None
        self._owners: OrderedDict[str, str] = OrderedDict(owners or {})
        self._max = max_orders
        self._lock = threading.Lock()

    def _owner(self, order_number: str, phone: str) -> str | None:
        with self._lock:
            owner = self._owners.get(order_number)
            if owner is None and not self._fixed:
                owner = self._owners[order_number] = phone
                while len(self._owners) > self._max:
                    self._owners.popitem(last=False)
            return owner

    def lookup(self, order_number: str, phone: str) -> dict[str, str] | None:
        if self._owner(order_number, phone) != phone:
            return None
        total = sum(int(c) for c in order_number if c.isdigit())
        return {
            "order_status": ORDER_STATUSES[total % len(ORDER_STATUSES)],
            "payment_status": PAYMENT_STATUSES[total % len(PAYMENT_STATUSES)],
        }
