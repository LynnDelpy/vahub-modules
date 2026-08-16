"""The calculator's safety and correctness, tested through the helper."""

from __future__ import annotations

import math

import pytest

from vahub_mod_calculator.server import CalcError, calculate, evaluate


def test_arithmetic_and_precedence() -> None:
    assert evaluate("(3.5 + 4) * 2") == 15.0
    assert evaluate("2 ** 10") == 1024
    assert evaluate("17 % 5") == 2
    assert evaluate("7 // 2") == 3
    assert evaluate("-3 + 4") == 1


def test_functions_and_constants() -> None:
    assert evaluate("sqrt(2)") == pytest.approx(math.sqrt(2))
    assert evaluate("log10(1000)") == pytest.approx(3.0)
    assert evaluate("max(1, 7, 3)") == 7
    assert evaluate("round(pi, 2)") == pytest.approx(3.14)
    assert evaluate("factorial(5)") == 120


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",       # no calls to arbitrary names
        "os.system('rm -rf /')",  # no attributes
        "open('x')",              # not on the allow list
        "x + 1",                  # unknown name
        "[1, 2, 3]",              # not an arithmetic node
        "1 if True else 2",       # no conditionals
        "9 ** 9 ** 9",            # exponent guard
        "",                       # empty
    ],
)
def test_unsafe_or_unsupported_is_refused(expr: str) -> None:
    with pytest.raises(CalcError):
        evaluate(expr)


def test_tool_returns_a_structured_result() -> None:
    ok = calculate("2 + 2")
    assert ok["ok"] is True and ok["result"] == 4
    bad = calculate("nonsense(")
    assert bad["ok"] is False and "error" in bad
