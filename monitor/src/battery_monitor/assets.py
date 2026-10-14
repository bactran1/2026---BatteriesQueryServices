from __future__ import annotations

import re
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

BUILD_TOKEN = "__BUILD_COMMIT__"
APP_VERSION_TOKEN = "__APP_VERSION__"
APP_VERSION_TITLE_TOKEN = "__APP_VERSION_TITLE__"


def app_version_label(build_commit: str, build_commit_date: str = "") -> tuple[str, str]:
    """Short label and hover title for the deployed commit, or "dev" without one."""
    commit = (build_commit or "").strip().lower()
    date = (build_commit_date or "").strip()
    if not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        return "dev", "dev"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = ""
    short = commit[:7]
    label = f"{short} · {date}" if date else short
    title = f"{commit} ({date})" if date else commit
    return label, title


def asset_version(build_commit: str, static_dir: Path | None = None) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]", "", build_commit or "")
    base = value or "unknown"
    if static_dir is None:
        return base

    digest = sha256(base.encode("utf-8"))
    for path in sorted(item for item in static_dir.rglob("*") if item.is_file()):
        digest.update(path.relative_to(static_dir).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return f"{base}-{digest.hexdigest()[:12]}"


def cache_control_for(
    path: str, version: str | None, expected_version: str
) -> str | None:
    if path == "/" or path == "/healthz" or path.startswith("/api/"):
        return "no-store"
    if path.startswith("/static/"):
        if version and version == asset_version(expected_version):
            return "public, max-age=31536000, immutable"
        return "no-cache"
    return None


@lru_cache(maxsize=8)
def render_index(
    index_path: Path,
    version: str,
    build_commit: str = "",
    build_commit_date: str = "",
) -> str:
    label, title = app_version_label(build_commit, build_commit_date)
    return (
        index_path.read_text(encoding="utf-8")
        .replace(BUILD_TOKEN, asset_version(version))
        .replace(APP_VERSION_TITLE_TOKEN, title)
        .replace(APP_VERSION_TOKEN, label)
    )
