"""Tests for pure helpers on the Signal client (no browser required)."""

from src.platforms.signal_client import SignalClient


def test_normalize_phone_adds_us_country_code():
    client = SignalClient()
    assert client._normalize_phone("5551234567") == "+15551234567"


def test_normalize_phone_strips_formatting():
    client = SignalClient()
    assert client._normalize_phone("(555) 123-4567") == "+15551234567"


def test_normalize_phone_preserves_existing_plus():
    client = SignalClient()
    assert client._normalize_phone("+447911123456") == "+447911123456"


def test_normalize_phone_prefixes_plus_for_intl_without_country_logic():
    client = SignalClient()
    # 12 digits, no leading +, not 10-digit US -> just gets a leading +
    assert client._normalize_phone("447911123456") == "+447911123456"


def test_message_fingerprint_is_deterministic_and_time_independent():
    a = SignalClient._message_fingerprint("+1555", "hello there")
    b = SignalClient._message_fingerprint("+1555", "hello there")
    # Same inputs must yield the same id across polls (the original bug folded
    # in datetime.now(), so dedup never worked).
    assert a == b
    assert a.startswith("fp:")


def test_message_fingerprint_varies_by_content_and_sender():
    base = SignalClient._message_fingerprint("+1555", "hello")
    assert base != SignalClient._message_fingerprint("+1555", "goodbye")
    assert base != SignalClient._message_fingerprint("+1666", "hello")


def test_message_fingerprint_tolerates_unknown_sender():
    fp = SignalClient._message_fingerprint(None, "hello")
    assert fp.startswith("fp:")
