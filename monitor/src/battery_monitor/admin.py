"""Admin authentication and runtime-editable settings for the monitor.

Everything here uses only the standard library. The dashboard stays public;
these helpers gate a separate ``/admin`` page and the ``/api/admin/*`` routes.

Auth model
----------
* The admin password comes from ``BQM_ADMIN_PASSWORD`` unless an operator has
  set one through the panel (stored as a PBKDF2 hash in the database metadata,
  which then takes precedence). When neither exists, admin is *disabled* and
  every login attempt fails closed.
* A successful login issues an HMAC-signed, time-limited token stored in an
  HttpOnly ``SameSite=Strict`` cookie. The same token embeds a CSRF value that
  mutating requests must echo back in the ``X-CSRF-Token`` header
  (double-submit), so a signed cookie alone cannot drive a state change.
* The signing secret is ``BQM_ADMIN_SECRET`` if set, otherwise a random secret
  generated once and persisted in the database metadata.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from .config import BatteryProfile, Settings
from .storage import RetentionStore

SESSION_COOKIE = "bqm_admin"
SESSION_TTL_SECONDS = 8 * 60 * 60
_PBKDF2_ITERATIONS = 240_000
_SECRET_KEY = "admin_secret"
_PASSWORD_KEY = "admin_password_hash"
_SETTINGS_KEY = "admin_settings"

DEFAULT_GLOW_STRENGTH = 0.05
MAX_GLOW_STRENGTH = 1.5
DEFAULT_LINE_GLOW = True

DEFAULT_SESSION_MINUTES = 30
MIN_SESSION_MINUTES = 1
MAX_SESSION_MINUTES = 24 * 60

MAX_BATTERY_RESERVE_PERCENT = 90


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
    except (ValueError, AttributeError):
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    try:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected_hex)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class AdminAuth:
    def __init__(
        self,
        store: RetentionStore,
        env_password: str | None = None,
        env_secret: str | None = None,
    ) -> None:
        self._store = store
        self._env_password = (env_password if env_password is not None
                              else os.getenv("BQM_ADMIN_PASSWORD")) or None
        self._env_secret = (env_secret if env_secret is not None
                            else os.getenv("BQM_ADMIN_SECRET")) or None

    def is_configured(self) -> bool:
        return bool(self._env_password) or self._store.get_metadata(_PASSWORD_KEY) is not None

    def _secret(self) -> bytes:
        if self._env_secret:
            return self._env_secret.encode("utf-8")
        stored = self._store.get_metadata(_SECRET_KEY)
        if stored is None:
            stored = secrets.token_hex(32)
            self._store.set_metadata(_SECRET_KEY, stored)
        return stored.encode("utf-8")

    def verify_login(self, password: str) -> bool:
        if not password:
            return False
        stored_hash = self._store.get_metadata(_PASSWORD_KEY)
        if stored_hash is not None:
            return verify_password(password, stored_hash)
        if self._env_password is not None:
            return hmac.compare_digest(
                password.encode("utf-8"), self._env_password.encode("utf-8")
            )
        return False

    def set_password(self, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self._store.set_metadata(_PASSWORD_KEY, hash_password(new_password))

    def issue_token(
        self,
        now: float | None = None,
        ttl_seconds: int | None = None,
        csrf: str | None = None,
    ) -> tuple[str, str]:
        """Return ``(cookie_token, csrf_token)`` for a session.

        ``ttl_seconds`` sets how long the token is valid (defaults to the
        8-hour cap). Pass an existing ``csrf`` to slide an active session
        forward without rotating its CSRF token.
        """
        issued = int(now if now is not None else time.time())
        ttl = int(ttl_seconds) if ttl_seconds is not None else SESSION_TTL_SECONDS
        csrf = csrf or secrets.token_hex(16)
        payload = {"exp": issued + ttl, "csrf": csrf}
        body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(self._secret(), body.encode("ascii"), hashlib.sha256).digest()
        return f"{body}.{_b64encode(signature)}", csrf

    def verify_token(self, token: str | None, now: float | None = None) -> dict[str, Any] | None:
        if not token or "." not in token:
            return None
        body, _, signature = token.partition(".")
        try:
            expected = hmac.new(self._secret(), body.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_b64decode(signature), expected):
                return None
            payload = json.loads(_b64decode(body))
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        current = int(now if now is not None else time.time())
        if int(payload.get("exp", 0)) < current:
            return None
        return payload


# ---------------------------------------------------------------------------
# Runtime-editable settings (persisted overrides over the env defaults)
# ---------------------------------------------------------------------------
class AdminSettings:
    def __init__(self, store: RetentionStore) -> None:
        self._store = store

    def _raw(self) -> dict[str, Any]:
        stored = self._store.get_metadata(_SETTINGS_KEY)
        if not stored:
            return {}
        try:
            value = json.loads(stored)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def _write(self, overrides: dict[str, Any]) -> None:
        self._store.set_metadata(_SETTINGS_KEY, json.dumps(overrides, separators=(",", ":")))

    def glow_strength(self) -> float:
        value = self._raw().get("energy_glow_strength")
        if not isinstance(value, (int, float)):
            return DEFAULT_GLOW_STRENGTH
        return max(0.0, min(MAX_GLOW_STRENGTH, float(value)))

    def line_glow(self) -> bool:
        value = self._raw().get("energy_line_glow")
        if not isinstance(value, bool):
            return DEFAULT_LINE_GLOW
        return value

    def effective_retention(self, base: Settings) -> int:
        value = self._raw().get("retention_days")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return base.retention_days
        return min(value, 3650)

    def effective_battery_reserve(self, base: Settings) -> int:
        value = self._raw().get("battery_reserve_percent")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return base.battery_reserve_percent
        return min(value, MAX_BATTERY_RESERVE_PERCENT)

    def session_minutes(self) -> int:
        value = self._raw().get("session_minutes")
        if not isinstance(value, int) or isinstance(value, bool):
            return DEFAULT_SESSION_MINUTES
        return max(MIN_SESSION_MINUTES, min(MAX_SESSION_MINUTES, value))

    def _effective_profiles(self, base: Settings) -> tuple[BatteryProfile, ...]:
        batteries = self._raw().get("batteries")
        if not isinstance(batteries, list) or not batteries:
            return base.battery_profiles
        by_id = {profile.id: profile for profile in base.battery_profiles}
        profiles: list[BatteryProfile] = []
        for index, entry in enumerate(batteries):
            if not isinstance(entry, dict):
                continue
            identifier = str(entry.get("id") or "").strip()
            if not identifier:
                continue
            fallback = by_id.get(identifier)
            profiles.append(
                BatteryProfile(
                    id=identifier,
                    name=str(entry.get("name") or (fallback.name if fallback else identifier)),
                    address=_coerce_int(
                        entry.get("address"),
                        fallback.address if fallback else index + 1,
                    ),
                    ip_address=_clean_optional(entry.get("ip_address")),
                    model=str(
                        entry.get("model")
                        or (fallback.model if fallback else "Eco-worthy server rack battery")
                    ),
                )
            )
        return tuple(profiles) if profiles else base.battery_profiles

    def effective_settings(self, base: Settings) -> Settings:
        overrides = self._raw()
        return dataclasses.replace(
            base,
            rack_name=str(overrides.get("rack_name") or base.rack_name),
            rack_builder=str(overrides.get("rack_builder") or base.rack_builder),
            rack_location=str(overrides.get("rack_location") or base.rack_location),
            collector_name=str(overrides.get("collector_name") or base.collector_name),
            retention_days=self.effective_retention(base),
            battery_reserve_percent=self.effective_battery_reserve(base),
            battery_profiles=self._effective_profiles(base),
        )

    def public_config(self, base: Settings) -> dict[str, Any]:
        effective = self.effective_settings(base)
        return {
            "rack_name": effective.rack_name,
            "rack_builder": effective.rack_builder,
            "rack_location": effective.rack_location,
            "collector_name": effective.collector_name,
            "retention_days": effective.retention_days,
            "battery_reserve_percent": effective.battery_reserve_percent,
            "energy_glow_strength": self.glow_strength(),
            "energy_line_glow": self.line_glow(),
            "session_minutes": self.session_minutes(),
            "batteries": [
                {
                    "id": profile.id,
                    "name": profile.name,
                    "address": profile.address,
                    "ip_address": profile.ip_address or "",
                    "model": profile.model,
                }
                for profile in effective.battery_profiles
            ],
        }

    def update(self, patch: dict[str, Any], base: Settings) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("Invalid configuration payload")
        overrides = self._raw()

        for key in ("rack_name", "rack_builder", "rack_location", "collector_name"):
            if key in patch:
                text = str(patch[key]).strip()
                if not text:
                    raise ValueError(f"{key} cannot be empty")
                overrides[key] = text[:120]

        if "retention_days" in patch:
            days = _coerce_int(patch["retention_days"], 0)
            if days < 1 or days > 3650:
                raise ValueError("retention_days must be between 1 and 3650")
            overrides["retention_days"] = days

        if "battery_reserve_percent" in patch:
            reserve = _coerce_int(patch["battery_reserve_percent"], -1)
            if reserve < 0 or reserve > MAX_BATTERY_RESERVE_PERCENT:
                raise ValueError(
                    f"battery_reserve_percent must be between 0 and {MAX_BATTERY_RESERVE_PERCENT}"
                )
            overrides["battery_reserve_percent"] = reserve

        if "session_minutes" in patch:
            minutes = _coerce_int(patch["session_minutes"], 0)
            if minutes < MIN_SESSION_MINUTES or minutes > MAX_SESSION_MINUTES:
                raise ValueError(
                    f"session_minutes must be between {MIN_SESSION_MINUTES} "
                    f"and {MAX_SESSION_MINUTES}"
                )
            overrides["session_minutes"] = minutes

        if "energy_glow_strength" in patch:
            try:
                glow = float(patch["energy_glow_strength"])
            except (TypeError, ValueError) as exc:
                raise ValueError("energy_glow_strength must be a number") from exc
            if glow < 0 or glow > MAX_GLOW_STRENGTH:
                raise ValueError(f"energy_glow_strength must be between 0 and {MAX_GLOW_STRENGTH}")
            overrides["energy_glow_strength"] = round(glow, 3)

        if "energy_line_glow" in patch:
            value = patch["energy_line_glow"]
            if isinstance(value, bool):
                overrides["energy_line_glow"] = value
            elif value in (0, 1, "true", "false", "0", "1"):
                overrides["energy_line_glow"] = value in (1, "true", "1")
            else:
                raise ValueError("energy_line_glow must be a boolean")

        if "batteries" in patch:
            overrides["batteries"] = _validate_batteries(patch["batteries"])

        self._write(overrides)
        return self.public_config(base)


def _validate_batteries(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("batteries must be a non-empty list")
    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("each battery must be an object")
        identifier = str(entry.get("id") or "").strip()
        if not identifier:
            raise ValueError("each battery needs an id")
        if identifier in seen_ids:
            raise ValueError(f"duplicate battery id: {identifier}")
        seen_ids.add(identifier)
        cleaned.append(
            {
                "id": identifier[:64],
                "name": str(entry.get("name") or identifier).strip()[:120],
                "address": _coerce_int(entry.get("address"), len(cleaned) + 1),
                "ip_address": _clean_optional(entry.get("ip_address")) or "",
                "model": str(entry.get("model") or "Eco-worthy server rack battery").strip()[:120],
            }
        )
    return cleaned


def _coerce_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_optional(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
