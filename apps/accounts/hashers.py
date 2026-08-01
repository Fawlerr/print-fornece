"""Temporary verification support for password_hash() bcrypt hashes from PHP."""
from __future__ import annotations

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare

try:  # Imported lazily in normal Django password checks, but keep an explicit error.
    import bcrypt
except ImportError:  # pragma: no cover - requirements guarantee bcrypt
    bcrypt = None


class LegacyPHPBcryptPasswordHasher(BasePasswordHasher):
    """Validate `$2y$` PHP bcrypt values and rehash them at the next login.

    Imported values are stored as `php_bcrypt$$2y$...`, so Django can identify
    the temporary hasher without changing the original bcrypt digest.
    """

    algorithm = "php_bcrypt"

    def salt(self) -> str:
        raise NotImplementedError("Legacy PHP hashes are imported, never created.")

    def encode(self, password: str, salt: str, iterations=None) -> str:
        raise NotImplementedError("Legacy PHP hashes are imported, never created.")

    def verify(self, password: str, encoded: str) -> bool:
        try:
            algorithm, legacy_hash = encoded.split("$", 1)
            if algorithm != self.algorithm or not legacy_hash.startswith("$2") or bcrypt is None:
                return False
            # bcrypt's Python package accepts $2b$ consistently; $2y$ is PHP's
            # equivalent marker, so normalize only for verification in memory.
            normalized_hash = legacy_hash.replace("$2y$", "$2b$", 1).encode("ascii")
            return bcrypt.checkpw(password.encode("utf-8"), normalized_hash)
        except (TypeError, ValueError, UnicodeEncodeError):
            return False

    def safe_summary(self, encoded: str) -> dict[str, str]:
        try:
            _, legacy_hash = encoded.split("$", 1)
            parts = legacy_hash.split("$")
            work_factor = parts[2] if len(parts) > 2 else "?"
            digest = parts[-1] if parts else ""
        except ValueError:
            work_factor, digest = "?", ""
        return {
            "algorithm": self.algorithm,
            "work factor": work_factor,
            "hash": mask_hash(digest),
        }

    def must_update(self, encoded: str) -> bool:
        # Django calls the preferred PBKDF2 hasher after a successful check.
        return True

    def harden_runtime(self, password: str, encoded: str) -> None:
        # bcrypt's checkpw already performs the legacy work factor.  There is no
        # safe way to add PBKDF2 here without changing the legacy hash format.
        return None

