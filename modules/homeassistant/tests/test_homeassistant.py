from __future__ import annotations

from vahub_mod_homeassistant.server import _clamp, summarize_states

STATES = [
    {"entity_id": "light.living_room", "state": "on"},
    {"entity_id": "light.kitchen", "state": "off"},
    {"entity_id": "lock.front_door", "state": "locked"},
]


def test_domain_filter() -> None:
    result = summarize_states(STATES, "light", 50)
    assert [e["entity_id"] for e in result] == ["light.living_room", "light.kitchen"]


def test_trailing_dot_in_domain_is_tolerated() -> None:
    assert len(summarize_states(STATES, "light.", 50)) == 2


def test_limit_bounds_the_result() -> None:
    assert len(summarize_states(STATES, None, 1)) == 1


def test_unexpected_backend_shapes_do_not_raise() -> None:
    # Home Assistant is not trusted to return what its docs promise, and a
    # module that raises on a surprise takes its tool call down with it.
    assert summarize_states({"unexpected": True}, None, 10) == []
    assert summarize_states(None, None, 10) == []
    assert summarize_states(["not-a-dict", {"no_entity_id": 1}], None, 10) == []


def test_clamp_survives_model_shaped_arguments() -> None:
    assert _clamp("7", 50, 1, 200) == 7
    assert _clamp(9000, 50, 1, 200) == 200
    assert _clamp(None, 50, 1, 200) == 50
    assert _clamp("all of them", 50, 1, 200) == 50
