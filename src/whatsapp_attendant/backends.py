"""Order backend port. The demo ships a deterministic fake; production plugs in the store's ERP."""

from __future__ import annotations

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
    def lookup(self, order_number: str) -> dict[str, str]:
        """Fields used by the reply templates: order_status and payment_status."""
        ...


class FakeOrderBackend:
    """Every 6-digit order exists; its status is a pure function of the digits."""

    def lookup(self, order_number: str) -> dict[str, str]:
        total = sum(int(c) for c in order_number if c.isdigit())
        return {
            "order_status": ORDER_STATUSES[total % len(ORDER_STATUSES)],
            "payment_status": PAYMENT_STATUSES[total % len(PAYMENT_STATUSES)],
        }
