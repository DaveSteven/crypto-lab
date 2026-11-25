from scripts.probe_websocket import ProbeState, handle_bitbank_message, handle_json_message


def state(exchange_id: str) -> ProbeState:
    return ProbeState(exchange_id=exchange_id, started_ts_ms=1)


def test_okx_snapshot_and_contiguous_delta() -> None:
    result = state("okx")
    handle_json_message(
        "okx",
        {
            "arg": {"channel": "books"},
            "action": "snapshot",
            "data": [{"seqId": "10"}],
        },
        result,
    )
    handle_json_message(
        "okx",
        {
            "arg": {"channel": "books"},
            "action": "update",
            "data": [{"prevSeqId": "10", "seqId": "11"}],
        },
        result,
    )

    assert result.order_book_snapshot_received
    assert result.order_book_delta_received
    assert result.sequence_checked
    assert result.sequence_ok


def test_okx_detects_sequence_gap() -> None:
    result = state("okx")
    result._last_sequence = 10
    handle_json_message(
        "okx",
        {
            "arg": {"channel": "books"},
            "action": "update",
            "data": [{"prevSeqId": "12", "seqId": "13"}],
        },
        result,
    )

    assert not result.sequence_ok


def test_zero_quantity_delta_is_retained_as_order_book_delta() -> None:
    result = state("bybit")
    handle_json_message(
        "bybit",
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "data": {"u": 2, "a": [["100", "0"]], "b": []},
        },
        result,
    )

    assert result.order_book_delta_received


def test_bitbank_whole_and_diff_share_monotonic_sequence() -> None:
    result = state("bitbank")
    whole = (
        '42["message",{"room_name":"depth_whole_btc_jpy","message":{"data":'
        '{"asks":[],"bids":[],"sequenceId":"10"}}}]'
    )
    diff = (
        '42["message",{"room_name":"depth_diff_btc_jpy","message":{"data":'
        '{"a":[],"b":[],"s":"12"}}}]'
    )

    handle_bitbank_message(whole, result)
    handle_bitbank_message(diff, result)

    assert result.order_book_snapshot_received
    assert result.order_book_delta_received
    assert result.sequence_ok


def test_coinbase_advanced_trade_snapshot_and_update() -> None:
    result = state("coinbase")
    handle_json_message(
        "coinbase",
        {
            "channel": "l2_data",
            "sequence_num": 2,
            "events": [{"type": "snapshot", "updates": []}],
        },
        result,
    )
    handle_json_message(
        "coinbase",
        {
            "channel": "l2_data",
            "sequence_num": 3,
            "events": [{"type": "update", "updates": []}],
        },
        result,
    )

    assert result.order_book_snapshot_received
    assert result.order_book_delta_received
    assert result.sequence_checked
    assert result.sequence_ok


def test_coinbase_detects_connection_sequence_gap() -> None:
    result = state("coinbase")
    result._last_sequence = 2

    handle_json_message(
        "coinbase",
        {"channel": "ticker", "sequence_num": 4, "events": []},
        result,
    )

    assert not result.sequence_ok
