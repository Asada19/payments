from app.domain.services.retry import NextAction, decide_next_action


def test_success_always_acks() -> None:
    for attempt in (0, 1, 2, 5):
        decision = decide_next_action(attempt, ok=True)
        assert decision.action is NextAction.ACK
        assert decision.routing_key is None


def test_first_failure_retries_in_2s() -> None:
    decision = decide_next_action(0, ok=False)
    assert decision.action is NextAction.RETRY
    assert decision.delay_seconds == 2
    assert decision.routing_key == "payments.retry.2s"


def test_second_failure_retries_in_4s() -> None:
    decision = decide_next_action(1, ok=False)
    assert decision.action is NextAction.RETRY
    assert decision.delay_seconds == 4
    assert decision.routing_key == "payments.retry.4s"


def test_third_failure_goes_to_dlq() -> None:
    decision = decide_next_action(2, ok=False)
    assert decision.action is NextAction.DLQ
    assert decision.routing_key is None
