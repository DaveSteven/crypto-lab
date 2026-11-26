"""Shared PostgreSQL fixtures for API lifecycle tests."""

import os

import pytest
from sqlalchemy import create_engine

from crypto_lab.persistence import schema


class Clock:
    def __init__(self, now: int = 1_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def engine():
    url = os.getenv("CRYPTO_LAB_TEST_DATABASE_URL")
    if not url:
        pytest.skip("CRYPTO_LAB_TEST_DATABASE_URL is not configured")
    engine = create_engine(url)
    with engine.begin() as connection:
        for table in reversed(schema.metadata.sorted_tables):
            connection.execute(table.delete())
    yield engine
    engine.dispose()


@pytest.fixture
def clock() -> Clock:
    return Clock()
