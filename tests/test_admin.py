from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from battery_monitor.admin import (
    SESSION_TTL_SECONDS,
    AdminAuth,
    AdminSettings,
    hash_password,
    verify_password,
)
from battery_monitor.collector import CollectorClient
from battery_monitor.config import load_settings
from battery_monitor.service import MonitorService
from battery_monitor.storage import RetentionStore


class _AdminTestCase(unittest.TestCase):
    def make_store(self) -> RetentionStore:
        directory = tempfile.mkdtemp()
        # LIFO cleanup: close the SQLite connection *before* the temp dir is
        # removed, so Windows can unlink the still-open database file.
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        store = RetentionStore(Path(directory) / "monitor.sqlite3")
        store.initialize()
        self.addCleanup(store.close)
        return store


class PasswordHashingTests(unittest.TestCase):
    def test_hash_roundtrip(self) -> None:
        encoded = hash_password("correct horse battery")
        self.assertTrue(verify_password("correct horse battery", encoded))
        self.assertFalse(verify_password("wrong password", encoded))

    def test_verify_rejects_malformed(self) -> None:
        self.assertFalse(verify_password("x", "not-a-valid-hash"))


class AdminAuthTests(_AdminTestCase):
    def test_env_password_then_stored_hash_precedence(self) -> None:
        auth = AdminAuth(self.make_store(), env_password="s3cret-env")
        self.assertTrue(auth.is_configured())
        self.assertTrue(auth.verify_login("s3cret-env"))
        self.assertFalse(auth.verify_login("nope"))

        auth.set_password("brand-new-password")
        # Stored hash now wins over the env password.
        self.assertFalse(auth.verify_login("s3cret-env"))
        self.assertTrue(auth.verify_login("brand-new-password"))

    def test_unconfigured_admin_fails_closed(self) -> None:
        auth = AdminAuth(self.make_store(), env_password=None)
        self.assertFalse(auth.is_configured())
        self.assertFalse(auth.verify_login("anything"))

    def test_short_password_rejected(self) -> None:
        auth = AdminAuth(self.make_store(), env_password="env")
        with self.assertRaises(ValueError):
            auth.set_password("short")

    def test_token_roundtrip_expiry_and_tamper(self) -> None:
        auth = AdminAuth(self.make_store(), env_password="env", env_secret="fixed-secret")
        token, csrf = auth.issue_token(now=1000)

        payload = auth.verify_token(token, now=1000)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["csrf"], csrf)

        self.assertIsNone(auth.verify_token(token, now=1000 + SESSION_TTL_SECONDS + 1))
        self.assertIsNone(auth.verify_token(token + "x", now=1000))
        self.assertIsNone(auth.verify_token(None))
        self.assertIsNone(auth.verify_token("garbage"))

    def test_token_rejected_by_different_secret(self) -> None:
        store = self.make_store()
        token, _ = AdminAuth(store, env_secret="secret-a").issue_token(now=1000)
        other = AdminAuth(store, env_secret="secret-b")
        self.assertIsNone(other.verify_token(token, now=1000))

    def test_custom_ttl_and_csrf_preserving_slide(self) -> None:
        auth = AdminAuth(self.make_store(), env_password="env", env_secret="fixed")
        # A short TTL expires exactly when configured.
        token, csrf = auth.issue_token(now=1000, ttl_seconds=120)
        self.assertIsNotNone(auth.verify_token(token, now=1000 + 119))
        self.assertIsNone(auth.verify_token(token, now=1000 + 121))

        # Sliding the session forward keeps the same CSRF but extends expiry.
        slid, slid_csrf = auth.issue_token(now=1200, ttl_seconds=120, csrf=csrf)
        self.assertEqual(slid_csrf, csrf)
        slid_payload = auth.verify_token(slid, now=1200 + 119)
        self.assertEqual(slid_payload["csrf"], csrf)
        # ...and the original token is unaffected by the slide.
        self.assertIsNone(auth.verify_token(token, now=1200 + 1))


class AdminSettingsTests(_AdminTestCase):
    def test_defaults_and_glow_clamp(self) -> None:
        base = load_settings()
        store = self.make_store()
        admin = AdminSettings(store)
        self.assertAlmostEqual(admin.glow_strength(), 0.05)
        self.assertEqual(admin.effective_retention(base), base.retention_days)

        # update() validates strictly: an out-of-range glow value is rejected.
        with self.assertRaises(ValueError):
            admin.update({"energy_glow_strength": 99}, base)

        admin.update({"energy_glow_strength": 0.4}, base)
        self.assertAlmostEqual(admin.glow_strength(), 0.4)

        # glow_strength() still clamps defensively if a stored value is out of range.
        store.set_metadata("admin_settings", json.dumps({"energy_glow_strength": 99}))
        self.assertEqual(admin.glow_strength(), 1.5)

    def test_line_glow_override_and_validation(self) -> None:
        base = load_settings()
        store = self.make_store()
        admin = AdminSettings(store)
        # Disabled by default so the tubing/conduits stay glowless.
        self.assertFalse(admin.line_glow())
        self.assertFalse(admin.public_config(base)["energy_line_glow"])

        admin.update({"energy_line_glow": True}, base)
        self.assertTrue(admin.line_glow())
        self.assertTrue(admin.public_config(base)["energy_line_glow"])

        admin.update({"energy_line_glow": False}, base)
        self.assertFalse(admin.line_glow())

        # Non-boolean values are rejected.
        with self.assertRaises(ValueError):
            admin.update({"energy_line_glow": "sometimes"}, base)

        # line_glow() falls back to the default if a stored value is the wrong type.
        store.set_metadata("admin_settings", json.dumps({"energy_line_glow": "yes"}))
        self.assertFalse(admin.line_glow())

    def test_active_opacity_override_and_validation(self) -> None:
        base = load_settings()
        store = self.make_store()
        admin = AdminSettings(store)
        # Defaults to the standard active conduit opacity.
        self.assertAlmostEqual(admin.active_opacity(), 0.82)
        self.assertAlmostEqual(admin.public_config(base)["energy_active_opacity"], 0.82)

        admin.update({"energy_active_opacity": 0.3}, base)
        self.assertAlmostEqual(admin.active_opacity(), 0.3)
        self.assertAlmostEqual(admin.public_config(base)["energy_active_opacity"], 0.3)

        # Fully transparent (pulses only) is allowed.
        admin.update({"energy_active_opacity": 0}, base)
        self.assertAlmostEqual(admin.active_opacity(), 0.0)

        # Out-of-range values are rejected at write time...
        for bad in (-0.1, 1.5):
            with self.assertRaises(ValueError):
                admin.update({"energy_active_opacity": bad}, base)
        # ...and a non-number is rejected too.
        with self.assertRaises(ValueError):
            admin.update({"energy_active_opacity": "opaque"}, base)

        # active_opacity() clamps a corrupt stored value defensively.
        store.set_metadata("admin_settings", json.dumps({"energy_active_opacity": 9}))
        self.assertAlmostEqual(admin.active_opacity(), 1.0)

    def test_battery_reserve_override_and_validation(self) -> None:
        base = load_settings()
        store = self.make_store()
        admin = AdminSettings(store)
        # Defaults to the env-configured discharge floor.
        self.assertEqual(admin.effective_battery_reserve(base), base.battery_reserve_percent)

        # A DoD-100% inverter is represented by a 0% reserve.
        admin.update({"battery_reserve_percent": 0}, base)
        self.assertEqual(admin.effective_battery_reserve(base), 0)
        self.assertEqual(admin.public_config(base)["battery_reserve_percent"], 0)
        self.assertEqual(admin.effective_settings(base).battery_reserve_percent, 0)

        # Out-of-range values are rejected at write time...
        for bad in (-1, 91, 100):
            with self.assertRaises(ValueError):
                admin.update({"battery_reserve_percent": bad}, base)
        # ...but the getter clamps a corrupt stored value defensively.
        store.set_metadata("admin_settings", json.dumps({"battery_reserve_percent": 999}))
        self.assertEqual(admin.effective_battery_reserve(base), 90)

    def test_session_minutes_override_and_validation(self) -> None:
        from battery_monitor.admin import DEFAULT_SESSION_MINUTES

        base = load_settings()
        store = self.make_store()
        admin = AdminSettings(store)
        self.assertEqual(admin.session_minutes(), DEFAULT_SESSION_MINUTES)

        admin.update({"session_minutes": 15}, base)
        self.assertEqual(admin.session_minutes(), 15)
        self.assertEqual(admin.public_config(base)["session_minutes"], 15)

        # Out-of-range values are rejected at write time...
        for bad in (0, 1441, -5):
            with self.assertRaises(ValueError):
                admin.update({"session_minutes": bad}, base)
        # ...but the getter clamps a corrupt stored value defensively.
        store.set_metadata("admin_settings", json.dumps({"session_minutes": 99999}))
        self.assertEqual(admin.session_minutes(), 1440)

    def test_rack_and_retention_overrides(self) -> None:
        base = load_settings()
        admin = AdminSettings(self.make_store())
        admin.update({"rack_name": "Garage Rack", "retention_days": 30}, base)
        effective = admin.effective_settings(base)
        self.assertEqual(effective.rack_name, "Garage Rack")
        self.assertEqual(effective.retention_days, 30)
        self.assertEqual(admin.effective_retention(base), 30)

    def test_invalid_updates_raise(self) -> None:
        base = load_settings()
        admin = AdminSettings(self.make_store())
        with self.assertRaises(ValueError):
            admin.update({"retention_days": 0}, base)
        with self.assertRaises(ValueError):
            admin.update({"rack_name": "   "}, base)
        with self.assertRaises(ValueError):
            admin.update({"batteries": []}, base)
        with self.assertRaises(ValueError):
            admin.update({"batteries": [{"id": "a"}, {"id": "a"}]}, base)

    def test_battery_inventory_override(self) -> None:
        base = load_settings()
        admin = AdminSettings(self.make_store())
        admin.update(
            {
                "batteries": [
                    {"id": "rack-9", "name": "Nine", "address": 9, "ip_address": "10.0.0.9", "model": "X"},
                ]
            },
            base,
        )
        effective = admin.effective_settings(base)
        self.assertEqual(len(effective.battery_profiles), 1)
        profile = effective.battery_profiles[0]
        self.assertEqual(profile.id, "rack-9")
        self.assertEqual(profile.address, 9)
        self.assertEqual(profile.ip_address, "10.0.0.9")
        config = admin.public_config(base)
        self.assertEqual(config["batteries"][0]["name"], "Nine")


class StorageAdminOpsTests(_AdminTestCase):
    def test_integrity_purge_and_backup(self) -> None:
        store = self.make_store()
        store.insert_snapshot(_sample_snapshot())
        self.assertGreater(store.stats(retention_days=1095)["row_count"], 0)

        integrity = store.integrity_check()
        self.assertTrue(integrity["ok"])

        backup = store.backup_bytes()
        self.assertTrue(backup.startswith(b"SQLite format 3"))

        deleted = store.purge_all()
        self.assertGreaterEqual(deleted["readings"], 1)
        self.assertEqual(store.stats(retention_days=1095)["row_count"], 0)


class ServiceControlTests(_AdminTestCase):
    def test_pause_resume_and_retention_provider(self) -> None:
        base = load_settings()
        collector = CollectorClient(base_url="http://collector.invalid")
        service = MonitorService(
            settings=base,
            store=self.make_store(),
            collector=collector,
            retention_provider=lambda: 42,
        )
        self.assertFalse(service.paused)
        service.pause()
        self.assertTrue(service.paused)
        service.resume()
        self.assertFalse(service.paused)
        self.assertEqual(service._retention_days(), 42)

    def test_retention_provider_falls_back(self) -> None:
        base = load_settings()
        collector = CollectorClient(base_url="http://collector.invalid")

        def _boom() -> int:
            raise RuntimeError("boom")

        service = MonitorService(
            settings=base, store=self.make_store(), collector=collector, retention_provider=_boom
        )
        # A failing provider must not crash pruning; fall back to settings.
        self.assertEqual(service._retention_days(), base.retention_days)


def _sample_snapshot() -> dict:
    return {
        "service": {"source": "collector"},
        "batteries": [
            {
                "id": "rack-1",
                "address": 1,
                "status": "ok",
                "last_reading": {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "voltage_v": 53.4,
                    "current_a": -5.0,
                    "power_w": -267.0,
                    "soc_percent": 74.5,
                },
            }
        ],
    }
