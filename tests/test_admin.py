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
