from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class NextAction(StrEnum):
    ACK = "ack"
    RETRY = "retry"
    DLQ = "dlq"


@dataclass(frozen=True)
class Decision:
    action: NextAction
    delay_seconds: int | None = None
    routing_key: str | None = None


def decide_next_action(attempt: int, ok: bool) -> Decision:
    if ok:
        return Decision(action=NextAction.ACK)
    if attempt <= 0:
        return Decision(
            action=NextAction.RETRY, delay_seconds=2, routing_key="payments.retry.2s"
        )
    if attempt == 1:
        return Decision(
            action=NextAction.RETRY, delay_seconds=4, routing_key="payments.retry.4s"
        )
    return Decision(action=NextAction.DLQ)
