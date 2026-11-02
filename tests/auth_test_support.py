"""Test-only revocation stores. Never imported by application code."""
from datetime import datetime
import sqlite3

from backend.auth import create_auth_router


class MemoryRevocationStore:
    def __init__(self):
        self.revoked = {}
        self.fail_read = False
        self.fail_write = False
        self.discard_write = False

    def is_revoked(self, jti):
        if self.fail_read:
            raise RuntimeError("test revocation lookup failure")
        return jti in self.revoked

    def revoke(self, jti, expires_at):
        if self.fail_write:
            raise RuntimeError("test revocation write failure")
        if not self.discard_write:
            self.revoked[jti] = expires_at


def revocations_for(store):
    if not hasattr(store, "_test_revocations"):
        store._test_revocations = MemoryRevocationStore()
    return store._test_revocations


def create_test_auth_router(*, store, **kwargs):
    return create_auth_router(store=store, revocation_store=revocations_for(store), **kwargs)


class SqliteTestRevocations:
    """Cross-process contract test only. Not the proposed PostgreSQL adapter."""
    def __init__(self, path):
        self.path = str(path)

    def is_revoked(self, jti):
        with sqlite3.connect(self.path) as conn:
            return conn.execute("SELECT 1 FROM revoked WHERE jti = ?", (jti,)).fetchone() is not None

    def revoke(self, jti: str, expires_at: datetime):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO revoked (jti, expires_at) VALUES (?, ?) ON CONFLICT(jti) DO NOTHING",
                         (jti, expires_at.timestamp()))
