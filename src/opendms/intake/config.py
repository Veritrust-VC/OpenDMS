"""Input channel configuration — a YAML file, no GUI.

Path: OPENDMS_INTAKE_CONFIG (default /etc/opendms/ievade.yaml). Re-read when the
file changes, so a channel can be switched on or off without a rebuild.
Secrets are never in the file: a channel names the environment variable that
holds its password (`parole_env`).

    registrs_publiskais_url: https://dokregistrs.example.lv
    kanali:
      - id: epasts
        veids: epasts                # epasts | tiessaistes-forma
        ieslegts: true
        imap: {host: mail.example.lv, port: 993, ssl: true, lietotajs: dvs@example.lv, mape: INBOX}
        smtp: {host: mail.example.lv, port: 587, starttls: true, no_adreses: dvs@example.lv}
        parole_env: OPENDMS_INTAKE_EMAIL_PASSWORD
        intervals_s: 60
        atlautie_sutitaji: ["*@example.lv"]   # empty or missing = everyone
        apstiprinajums: {ieslegts: true, gaidit_s: 900}
      - id: forma
        veids: tiessaistes-forma
        ieslegts: true
        max_mb: 20
"""

from __future__ import annotations

import fnmatch
import logging
import os
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATH = "/etc/opendms/ievade.yaml"
KINDS = ("epasts", "tiessaistes-forma")

_cache: dict[str, Any] = {"mtime": None, "data": {}}


def path() -> str:
    return os.environ.get("OPENDMS_INTAKE_CONFIG", DEFAULT_PATH)


def load() -> dict[str, Any]:
    p = path()
    try:
        mtime = os.path.getmtime(p)
    except OSError:
        return {"kanali": [], "_nav": p}
    if _cache["mtime"] != mtime:
        try:
            with open(p, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            for ch in data.get("kanali") or []:
                if ch.get("veids") not in KINDS:
                    logger.warning("intake: channel %s has unknown kind %s", ch.get("id"), ch.get("veids"))
            _cache.update(mtime=mtime, data=data)
        except Exception as exc:
            logger.error("intake: cannot read %s: %s", p, exc)
            return {"kanali": [], "_kluda": str(exc)}
    return _cache["data"]


def channels(kind: Optional[str] = None, enabled_only: bool = True) -> list[dict]:
    out = []
    for ch in load().get("kanali") or []:
        if enabled_only and not ch.get("ieslegts", True):
            continue
        if kind and ch.get("veids") != kind:
            continue
        out.append(ch)
    return out


def channel(cid: str) -> Optional[dict]:
    return next((c for c in channels(enabled_only=False) if c.get("id") == cid), None)


def register_public_url() -> str:
    return (load().get("registrs_publiskais_url") or os.environ.get("OPENDMS_REGISTER_PUBLIC_URL") or "").rstrip("/")


def password(ch: dict) -> str:
    env = ch.get("parole_env")
    return os.environ.get(env, "") if env else ""


def sender_allowed(ch: dict, address: str) -> bool:
    allowed = ch.get("atlautie_sutitaji") or []
    if not allowed:
        return True
    a = (address or "").lower()
    return any(fnmatch.fnmatch(a, pat.lower()) for pat in allowed)


def public_view(ch: dict) -> dict:
    """Channel description without secrets (for the read-only status API)."""
    v = {k: ch.get(k) for k in ("id", "veids", "ieslegts", "intervals_s", "max_mb", "nosaukums")}
    if ch.get("veids") == "epasts":
        v["adrese"] = (ch.get("smtp") or {}).get("no_adreses") or (ch.get("imap") or {}).get("lietotajs")
        v["imap"] = {k: (ch.get("imap") or {}).get(k) for k in ("host", "port", "mape")}
        v["paroleIestatita"] = bool(password(ch))
        v["atlautieSutitaji"] = ch.get("atlautie_sutitaji") or []
        v["apstiprinajums"] = ch.get("apstiprinajums") or {}
    return v
