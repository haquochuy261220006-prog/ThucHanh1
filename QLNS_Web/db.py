"""Compatibility import; database operations live in database.db."""
from database.db import execute, execute_batches, query, scalar

__all__ = ["execute", "execute_batches", "query", "scalar"]
