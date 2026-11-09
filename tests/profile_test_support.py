"""Test-only in-memory ProfileStore. Never imported by application code."""
from dataclasses import replace
from datetime import datetime, timezone


class MemoryProfileStore:
    def __init__(self):
        self.rows = {}
        self.fail = False

    def _check(self):
        if self.fail:
            raise RuntimeError("test profile store failure")

    def get(self, user_id):
        self._check()
        return self.rows.get(str(user_id))

    def exists(self, user_id):
        self._check()
        return str(user_id) in self.rows

    def upsert(self, profile):
        self._check()
        stored = replace(profile, updated_at=datetime.now(timezone.utc))
        self.rows[profile.user_id] = stored
        return stored

    def raw_bytes(self):
        """Every stored ciphertext byte, for "no plaintext at rest" checks."""
        return b"".join(
            row.name_enc + row.dept_enc + row.phone_enc + row.address_enc for row in self.rows.values()
        )
