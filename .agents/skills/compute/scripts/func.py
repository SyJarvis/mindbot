#!/usr/bin/env python3
"""
Compute Skill Script
Provides math computation functions: sigmoid, evaluate, factorial, fibonacci, gcd, lcm, power, sqrt.

Input:  JSON via stdin with {"function": "<name>", "arguments": {...}}
Output: JSON via stdout with {"result": <value>, "error": null|string}
"""

import json
import math
import sys


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def evaluate(expression: str):
    """Safely evaluate a math expression using a restricted set of operations."""
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "pow": pow, "sum": sum,
        "pi": math.pi, "e": math.e,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "log2": math.log2, "exp": math.exp,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "asin": math.asin, "acos": math.acos, "atan": math.atan,
        "ceil": math.ceil, "floor": math.floor,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return result
    except Exception as exc:
        raise ValueError(f"Cannot evaluate expression: {exc}") from exc


def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("factorial requires a non-negative integer")
    return math.factorial(n)


def fibonacci(n: int) -> int:
    if n < 0:
        raise ValueError("fibonacci requires a non-negative index")
    if n == 0:
        return 0
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b


def gcd(a: int, b: int) -> int:
    return math.gcd(a, b)


def lcm(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // math.gcd(a, b)


def power(base: float, exp: float) -> float:
    return math.pow(base, exp)


def sqrt(x: float) -> float:
    if x < 0:
        raise ValueError("sqrt requires a non-negative number")
    return math.sqrt(x)


FUNCTIONS = {
    "sigmoid": (sigmoid, ["x"]),
    "evaluate": (evaluate, ["expression"]),
    "factorial": (factorial, ["n"]),
    "fibonacci": (fibonacci, ["n"]),
    "gcd": (gcd, ["a", "b"]),
    "lcm": (lcm, ["a", "b"]),
    "power": (power, ["base", "exp"]),
    "sqrt": (sqrt, ["x"]),
}


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({"result": None, "error": "No input provided"}))
            sys.exit(1)

        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"result": None, "error": f"Invalid JSON input: {exc}"}))
        sys.exit(1)

    func_name = data.get("function")
    arguments = data.get("arguments", {})

    if not func_name:
        print(json.dumps({"result": None, "error": "Missing 'function' field"}))
        sys.exit(1)

    entry = FUNCTIONS.get(func_name)
    if entry is None:
        available = ", ".join(sorted(FUNCTIONS))
        print(json.dumps({"result": None, "error": f"Unknown function '{func_name}'. Available: {available}"}))
        sys.exit(1)

    func, param_names = entry

    # Build positional args from the argument dict in declared order
    try:
        args = []
        for p in param_names:
            if p not in arguments:
                raise ValueError(f"Missing required argument '{p}'")
            args.append(arguments[p])
    except ValueError as exc:
        print(json.dumps({"result": None, "error": str(exc)}))
        sys.exit(1)

    # Execute
    try:
        result = func(*args)
        print(json.dumps({"result": result, "error": None}))
    except Exception as exc:
        print(json.dumps({"result": None, "error": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
