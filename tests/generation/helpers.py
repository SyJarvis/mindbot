"""Test helper callables for DynamicToolExecutor callable-mode tests."""


def add(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


def div(a: float, b: float) -> float:
    """Divide a by b."""
    return a / b


async def async_echo(message: str) -> str:
    """Async echo of the message."""
    return message
