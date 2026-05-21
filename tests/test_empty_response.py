"""Tests for `_is_empty_response` — the helper that distinguishes
'account has no positions/transactions' (benign) from real errors."""
from __future__ import annotations

from types import SimpleNamespace

from etrade_mcp.etrade_client import _is_empty_response


def test_http_204_response_detected_via_exception_object():
    """The preferred path: dispatch on the underlying HTTPError's status_code,
    not on substring matching the stringified message."""
    err = Exception("anything")
    err.response = SimpleNamespace(status_code=204)
    assert _is_empty_response(err) is True


def test_http_200_with_unrelated_message_not_treated_as_empty():
    """A successful response (or one with a non-204 status) is NOT
    misclassified just because the error message contains '204'."""
    err = Exception("Position ID 1204 not found")
    err.response = SimpleNamespace(status_code=400)
    assert _is_empty_response(err) is False


def test_json_decode_value_error_detected():
    """pyetrade raises ValueError('Expecting value: line 1 column 1') when
    E*TRADE returns an empty body. Treat as empty response."""
    err = ValueError("Expecting value: line 1 column 1 (char 0)")
    assert _is_empty_response(err) is True


def test_unrelated_value_error_not_misclassified():
    err = ValueError("invalid literal for int() with base 10: 'foo'")
    assert _is_empty_response(err) is False


def test_substring_fallback_uses_anchored_markers():
    """Last-resort substring matching uses anchored phrases that won't
    collide with unrelated errors containing bare '204' or 'No'."""
    # Anchored markers match:
    assert _is_empty_response("HTTP 204 No Content") is True
    assert _is_empty_response("No positions for account ABC123") is True
    assert _is_empty_response("No Transactions found") is True
    # Bare numeric/word collisions do NOT match (the old code did match
    # any of these — regression check):
    assert _is_empty_response("transaction id 12047 not found") is False
    assert _is_empty_response("No matching symbol") is False


def test_exception_without_response_attr_falls_through_to_substring():
    """A bare Exception with no `.response` attribute is stringified and
    falls through to the substring check."""
    err = Exception("HTTP 204 No Content")
    assert _is_empty_response(err) is True
