# calculator

Evaluate arithmetic safely. A language model is unreliable at multi-digit
arithmetic and confidently wrong about it, so this gives it a real calculator.

## Tools

- `calculate(expression)`: evaluate an arithmetic expression and return the
  number. Supports `+ - * / // % **` and parentheses, the functions `sqrt`,
  `sin`, `cos`, `tan`, `log`, `log10`, `exp`, `floor`, `ceil`, `factorial`,
  `abs`, `round`, `min`, `max` and more, and the constants `pi`, `e`, `tau`.

## Safety

The expression comes from the model and is never passed to `eval`. It is parsed
into a syntax tree and walked, allowing only numbers, arithmetic operators, the
listed functions and constants. Names, attributes, calls to anything else, and
oversized exponents are refused. There is no configuration and no network.

## Policy

```yaml
calculator.calculate:
  class: read
  constraints:
    expression: { max_len: 500 }
```
