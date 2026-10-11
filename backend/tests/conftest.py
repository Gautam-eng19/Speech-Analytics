"""Shared pytest fixtures for the backend tests."""
import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _reset_dependency_overrides():
    """Every test starts and ends without FastAPI dependency overrides (fake pipelines / caches)."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
