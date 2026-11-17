"""Configurações do usuário guardadas no SQLite (tabela settings)."""
from __future__ import annotations

import json
import re

from flask import current_app

from ..extensions import db
from ..models import Setting

# limites: (mínimo, máximo)
LIMITS = {
    "check_interval_minutes": (30, 1440),
    "min_change_percent": (0.5, 50.0),
    "min_change_cents": (0, 100000),
    "notify_max_per_hour": (1, 60),
}

# Tipos de alerta e se vêm ligados por padrão
NOTIFY_KINDS = {
    "target_reached": True,
    "price_drop": True,
    "lowest_ever": True,
    "opportunity": True,
    "coupon_available": True,
    "back_in_stock": True,
    "better_store": True,
    "price_increase": False,
    "out_of_stock": False,
    "misleading_promo": False,
}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def defaults() -> dict:
    return {
        "monitor_enabled": True,
        "check_interval_minutes": current_app.config["CHECK_INTERVAL_MINUTES"],
        # Oscilações menores que isto não geram eventos de queda/aumento.
        "min_change_percent": 2.0,
        "min_change_cents": 500,
        # Notificações
        "notify_enabled": True,
        "notify_kinds": dict(NOTIFY_KINDS),
        "notify_quiet_enabled": False,
        "notify_quiet_start": "23:00",
        "notify_quiet_end": "07:00",
        "notify_max_per_hour": 10,
    }


def get_all() -> dict:
    out = defaults()
    for key in out:
        row = db.session.get(Setting, f"cfg.{key}")
        if row and row.value is not None:
            try:
                value = json.loads(row.value)
            except ValueError:
                continue
            # novos tipos de alerta ganham o padrão mesmo com preferências antigas salvas
            out[key] = {**out[key], **value} if isinstance(out[key], dict) and isinstance(value, dict) else value
    return out


def get(key: str):
    return get_all()[key]


def validate(patch: dict) -> tuple[dict, dict]:
    clean, errors = {}, {}
    for key, value in patch.items():
        if key not in defaults():
            errors[key] = "Configuração desconhecida."
            continue
        if key in ("monitor_enabled", "notify_enabled", "notify_quiet_enabled"):
            if not isinstance(value, bool):
                errors[key] = "Valor inválido."
            else:
                clean[key] = value
            continue
        if key == "notify_kinds":
            if not isinstance(value, dict) or any(
                k not in NOTIFY_KINDS or not isinstance(v, bool) for k, v in value.items()
            ):
                errors[key] = "Valor inválido."
            else:
                clean[key] = {**get_all()["notify_kinds"], **value}
            continue
        if key in ("notify_quiet_start", "notify_quiet_end"):
            if not isinstance(value, str) or not HHMM.match(value):
                errors[key] = "Use o formato HH:MM."
            else:
                clean[key] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors[key] = "Informe um número."
            continue
        lo, hi = LIMITS[key]
        if not lo <= value <= hi:
            errors[key] = f"Use um valor entre {lo:g} e {hi:g}."
            continue
        clean[key] = int(value) if key != "min_change_percent" else float(value)
    return clean, errors


def update(clean: dict) -> dict:
    for key, value in clean.items():
        row = db.session.get(Setting, f"cfg.{key}")
        if row:
            row.value = json.dumps(value)
        else:
            db.session.add(Setting(key=f"cfg.{key}", value=json.dumps(value)))
    db.session.commit()
    return get_all()
