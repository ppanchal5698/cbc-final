"""Runtime configuration for the CBC Ops-Hub API.

Values come from the environment (see .env.example). Everything has a working
local default so the service starts against docker-compose without setup.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from cbc.shared.paths import pricebook_dir, reference_dir, repo_root, storage_root

REPO_ROOT = repo_root()

# The committed local-development values. Named so the production guard below and
# the defaults above cannot drift apart.
DEV_SECRET = "cbc-local-dev-key-change-me"
DEV_MONGO_PASSWORD = "cbc_local_dev"


def _path(env_var: str, default: str) -> Path:
    raw = os.environ.get(env_var, default)
    path = Path(raw)
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


class Settings:
    """Process settings. Read once at import, overridable in tests."""

    def __init__(self) -> None:
        self.mongodb_uri = os.environ.get(
            "MONGODB_URI",
            f"mongodb://cbc:{DEV_MONGO_PASSWORD}@localhost:27017/cbc_opshub?authSource=admin",
        )
        self.mongodb_db = os.environ.get("MONGODB_DB", "cbc_opshub")
        self.repo_root = REPO_ROOT
        self.storage_root = storage_root()
        self.pricebook_dir = pricebook_dir()
        self.reference_dir = reference_dir()
        self.templates_dir = _path("TEMPLATES_DIR", "templates")
        self.cors_origins = [
            origin.strip()
            for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
            if origin.strip()
        ]
        self.max_upload_mb = int(os.environ.get("MAX_UPLOAD_MB", "200"))
        # Shared secret between the Next.js proxy and this API. Defaults to
        # APP_SECRET_KEY in local dev so docker-compose works without extra wiring.
        self.internal_api_token = os.environ.get(
            "INTERNAL_API_TOKEN",
            os.environ.get("APP_SECRET_KEY", DEV_SECRET),
        )
        self.internal_auth = os.environ.get("INTERNAL_AUTH", "token").strip().lower() or "token"
        self.service_audience = (
            os.environ.get("SERVICE_AUDIENCE", "platform").strip() or "platform"
        )
        self.internal_jwt_secret = os.environ.get(
            "INTERNAL_JWT_SECRET",
            self.internal_api_token,
        )
        self.internal_jwt_secret_previous = os.environ.get(
            "INTERNAL_JWT_SECRET_PREVIOUS", ""
        ).strip()
        self.app_env = os.environ.get("APP_ENV", "development")
        self._assert_production_secrets()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def _assert_production_secrets(self) -> None:
        """Refuse to run in production on the local-development defaults.

        Each of these is a full compromise on its own: the internal token bypasses
        NextAuth and lets any caller pick its own X-Actor, APP_SECRET_KEY is the
        Fernet key every stored provider credential is encrypted under, and the
        Mongo password is in the repository. They exist so `docker compose up`
        works with no setup, which is exactly why they must fail closed anywhere
        real rather than quietly stay in place.
        """
        if self.app_env.lower() not in ("production", "prod", "staging"):
            return

        insecure = []
        if not self.internal_api_token.strip():
            # Not the dev default, so the check below misses it - and an empty
            # token used to mean the middleware skipped the comparison entirely.
            insecure.append("INTERNAL_API_TOKEN (empty - that disables the check)")
        elif self.internal_api_token == DEV_SECRET:
            insecure.append("INTERNAL_API_TOKEN (or APP_SECRET_KEY, which it falls back to)")
        if self.internal_auth == "jwt" and (
            not self.internal_jwt_secret.strip() or self.internal_jwt_secret == DEV_SECRET
        ):
            insecure.append("INTERNAL_JWT_SECRET")
        if os.environ.get("APP_SECRET_KEY", DEV_SECRET) == DEV_SECRET:
            insecure.append("APP_SECRET_KEY")
        if DEV_MONGO_PASSWORD in self.mongodb_uri:
            insecure.append("MONGODB_URI (still carries the local-dev password)")
        readonly_password = os.environ.get("MONGODB_READONLY_PASSWORD", "cbc_catalog_ro_local_dev")
        if readonly_password == "cbc_catalog_ro_local_dev":
            insecure.append("MONGODB_READONLY_PASSWORD (still the repo default)")

        if insecure:
            raise RuntimeError(
                f"APP_ENV={self.app_env} but these still hold their local-development "
                "defaults: " + ", ".join(insecure) + ". Set them to real secrets "
                "(openssl rand -base64 32) before starting."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
