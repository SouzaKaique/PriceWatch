"""Manutenção local: integridade e backups do banco SQLite.

- Ao iniciar, roda `PRAGMA quick_check` e registra o resultado (exibido em /api/health).
- Backup diário consistente (API de backup do SQLite, segura com o app rodando) em
  backend/instance/backups/, mantendo os 7 mais recentes.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import text

from ..extensions import db

log = logging.getLogger(__name__)
KEEP_BACKUPS = 7
_integrity: dict = {"checked": False, "ok": None, "detail": None}


def db_file() -> Path | None:
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///") or ":memory:" in uri:
        return None
    return Path(uri.removeprefix("sqlite:///"))


def backups_dir() -> Path:
    return Path(current_app.instance_path) / "backups"


def check_integrity() -> dict:
    try:
        result = db.session.execute(text("PRAGMA quick_check")).scalar()
        ok = result == "ok"
        _integrity.update(checked=True, ok=ok, detail=None if ok else str(result)[:300])
    except Exception as exc:  # noqa: BLE001
        _integrity.update(checked=True, ok=False, detail=exc.__class__.__name__)
    if not _integrity["ok"]:
        log.error("Banco com problema de integridade: %s — restaure um backup de %s",
                  _integrity["detail"], backups_dir())
    return dict(_integrity)


def integrity() -> dict:
    return dict(_integrity)


def list_backups() -> list[Path]:
    d = backups_dir()
    return sorted(d.glob("pricewatch-*.db"), reverse=True) if d.exists() else []


def backup(force: bool = False) -> Path | None:
    """Cria um backup se o último tiver mais de 20 h (ou se `force`)."""
    src = db_file()
    if src is None or not src.exists():
        return None
    existing = list_backups()
    if existing and not force:
        age = datetime.now() - datetime.fromtimestamp(existing[0].stat().st_mtime)
        if age < timedelta(hours=20):
            return None
    d = backups_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = d / f"pricewatch-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(src) as source, sqlite3.connect(target) as dest:
        source.backup(dest)
    for old in list_backups()[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)
    log.info("Backup do banco criado: %s", target.name)
    return target


def status() -> dict:
    files = list_backups()
    return {
        "integrity": integrity(),
        "backups": len(files),
        "last_backup_at": datetime.fromtimestamp(files[0].stat().st_mtime).isoformat() if files else None,
        "backups_dir": str(backups_dir()),
    }
