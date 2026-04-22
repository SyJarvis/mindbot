"""Pytest configuration for memory tests."""

import pytest


@pytest.fixture()
def memory_base_path():
    """Provide a temporary base path for memory tests."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "memory"


@pytest.fixture()
def memory_content_path(memory_base_path):
    """Provide a content path for memory tests."""
    yield memory_base_path / "content"