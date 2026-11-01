"""A small evaluator for the GitHub Actions expressions the workflows use in job `if:` conditions, so tests can check
which events start a job instead of only matching the condition's text.

Covers: context paths (github.event.label.name, inputs.label), string/number/boolean/null literals, ==, !=, !, &&,
||, parentheses and startsWith/endsWith/contains. Follows GitHub's rules: a missing property is null; == on strings
ignores case; && and || return one of their operands; falsy values are null, false, 0, -0 and ''.
"""

from __future__ import annotations

import re

TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+(?:\.\d+)?)|(?P<op>&&|\|\||==|!=|[!(),])"
                   r"|(?P<name>[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*))")


def truthy(v) -> bool:
    return v not in (None, False, 0, "") and v is not False


def equal(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    return a == b


def evaluate(expr: str, contexts: dict):
    expr = expr.strip()
    if expr.startswith("${{") and expr.endswith("}}"):
        expr = expr[3:-2]
    tokens, pos = [], 0
    while pos < len(expr):
        if expr[pos:].strip() == "":
            break
        m = TOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise ValueError(f"cannot parse expression at: {expr[pos:pos + 30]!r}")
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    i = 0

    def peek():
        return tokens[i] if i < len(tokens) else (None, None)

    def take(expected=None):
        nonlocal i
        tok = peek()
        if expected is not None and tok[1] != expected:
            raise ValueError(f"expected {expected!r}, got {tok[1]!r}")
        i += 1
        return tok

    def lookup(path: str):
        if path in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[path]
        node = contexts
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        return node

    def primary():
        kind, val = take()
        if kind == "str":
            return val[1:-1].replace("''", "'")
        if kind == "num":
            return float(val) if "." in val else int(val)
        if val == "(":
            v = or_expr()
            take(")")
            return v
        if val == "!":
            return not truthy(primary())
        if kind == "name":
            if peek()[1] == "(":
                take("(")
                args = [or_expr()]
                while peek()[1] == ",":
                    take(",")
                    args.append(or_expr())
                take(")")
                a, b = (str(x or "").lower() for x in args[:2])
                return {"startsWith": a.startswith(b), "endsWith": a.endswith(b),
                        "contains": b in a}[val]
            return lookup(val)
        raise ValueError(f"unexpected token {val!r}")

    def comparison():
        left = primary()
        while peek()[1] in ("==", "!="):
            op = take()[1]
            right = primary()
            left = equal(left, right) if op == "==" else not equal(left, right)
        return left

    def and_expr():
        left = comparison()
        while peek()[1] == "&&":
            take()
            right = comparison()
            left = right if truthy(left) else left
        return left

    def or_expr():
        left = and_expr()
        while peek()[1] == "||":
            take()
            right = and_expr()
            left = left if truthy(left) else right
        return left

    value = or_expr()
    if i != len(tokens):
        raise ValueError(f"trailing tokens: {tokens[i:]}")
    return value


def runs(expr: str, contexts: dict) -> bool:
    """Whether a job with this `if:` starts for the given contexts."""
    return truthy(evaluate(expr, contexts))
