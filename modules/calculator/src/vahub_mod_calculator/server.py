"""The calculator module: evaluate arithmetic without eval().

A language model is unreliable at multi-digit arithmetic and confidently wrong
about it, so giving it a real calculator removes a whole class of mistake. The
expression comes from the model and is therefore untrusted, which is why this
never touches eval(): it parses the string into a syntax tree and walks it,
allowing only numbers, arithmetic operators, a short list of math functions, and
the constants pi and e. A name, an attribute, a call to anything else, or a
power large enough to hang the process is refused.
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("calculator")

# The only binary and unary operators allowed. Anything else in the tree is a
# refusal, not a best effort.
_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# factorial has no natural bound and grows super-exponentially, so factorial of a
# few million would build a number with millions of digits and hang the process.
# Cap the argument; a real calculation never needs more.
_MAX_FACTORIAL = 1000


def _factorial(n: Any) -> int:
    if not isinstance(n, int) or isinstance(n, bool):
        raise CalcError("factorial needs a whole number")
    if n < 0 or n > _MAX_FACTORIAL:
        raise CalcError(f"factorial argument must be between 0 and {_MAX_FACTORIAL}")
    return math.factorial(n)


# A curated, side-effect-free slice of the math module, plus the two constants a
# person actually types. abs/round/min/max are the builtins people expect.
_FUNCS: dict[str, Any] = {
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "log": math.log, "log2": math.log2, "log10": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil, "factorial": _factorial,
    "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot,
    "abs": abs, "round": round, "min": min, "max": max,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}

# A guard against `9**9**9` style expressions that would try to build a number
# too large to hold. Exponents above this are refused.
_MAX_EXPONENT = 1000


class CalcError(Exception):
    """A refusal a person can act on, not a stack trace."""


def _eval(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise CalcError("only numbers are allowed")
        return node.value
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise CalcError("that operator is not allowed")
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > _MAX_EXPONENT:
            raise CalcError("exponent is too large")
        return op(left, right)
    if isinstance(node, ast.UnaryOp):
        op = _UNARYOPS.get(type(node.op))
        if op is None:
            raise CalcError("that operator is not allowed")
        return op(_eval(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise CalcError("that function is not allowed")
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise CalcError(f"unknown name {node.id!r}")
    raise CalcError("that expression is not allowed")


def evaluate(expression: str) -> float:
    """Parse and evaluate one arithmetic expression, or raise CalcError."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("empty expression")
    if len(expression) > 500:
        raise CalcError("expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"could not parse the expression: {e.msg}") from e
    result = _eval(tree)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise CalcError("result is not a number")
    return result


@mcp.tool()
def calculate(expression: str) -> dict[str, Any]:
    """Evaluate an arithmetic expression and return the number.

    Use this for any calculation rather than doing the arithmetic yourself.
    Supports + - * / // % ** and parentheses, the functions sqrt, sin, cos, tan,
    log, log10, exp, floor, ceil, factorial, abs, round, min, max and others,
    and the constants pi, e, tau. Examples: "(3.5 + 4) * 2", "sqrt(2)",
    "log10(1000)", "15% of 200 -> 200 * 0.15".

    expression: the arithmetic to evaluate.
    """
    try:
        value = evaluate(expression)
    except CalcError as e:
        return {"ok": False, "error": str(e), "expression": expression}
    except (ArithmeticError, ValueError, TypeError, RecursionError) as e:
        # math domain (sqrt(-1)), overflow (exp(1000)), division by zero, and the
        # like are ordinary calculator errors, not module crashes.
        return {"ok": False, "error": str(e) or e.__class__.__name__, "expression": expression}
    return {"ok": True, "expression": expression, "result": value}


@mcp.tool(name="__health")
def health() -> dict[str, Any]:
    """Reserved health probe: pure computation, always available."""
    return {"ok": True, "backend": "local", "latency_ms": 0.0, "detail": None}


def run() -> None:
    mcp.run(transport="stdio")
