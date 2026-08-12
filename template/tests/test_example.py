from __future__ import annotations

from vahub_mod_example.server import health, shout


def test_shout_reverses_the_text() -> None:
    assert shout("abc").endswith("cba")


def test_health_returns_the_four_contract_keys() -> None:
    result = health()
    assert set(result) == {"ok", "backend", "latency_ms", "detail"}
    assert result["ok"] is True
