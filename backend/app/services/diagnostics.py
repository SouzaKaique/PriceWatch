"""Diagnóstico: uma lista de verificações com status ok / atenção / erro e o que fazer."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from flask import current_app
from sqlalchemy import func

from .. import scheduler
from ..extensions import db
from ..models import MonitorRun, NotificationLog, Offer, PriceEvent, Product, utcnow
from ..stores import STORES
from . import maintenance, notify, webpush
from . import settings as settings_svc


def _item(key: str, label: str, status: str, detail: str, hint: str | None = None) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint}


def run(include_scheduler: bool = True) -> list[dict]:
    out: list[dict] = []
    cfg = settings_svc.get_all()
    now = utcnow()

    # Banco
    integ = maintenance.check_integrity()
    counts = (
        db.session.scalar(db.select(func.count(Product.id))),
        db.session.scalar(db.select(func.count(Offer.id))),
    )
    out.append(_item("database", "Banco de dados", "ok" if integ["ok"] else "error",
                     f"Integridade {'ok' if integ['ok'] else 'com problemas: ' + str(integ['detail'])}; "
                     f"{counts[0]} produto(s), {counts[1]} oferta(s).",
                     None if integ["ok"] else "Pare o backend e restaure o backup mais recente (README › Backups)."))

    mstat = maintenance.status()
    if mstat["backups"]:
        out.append(_item("backups", "Backups", "ok",
                         f"{mstat['backups']} backup(s); último em {mstat['last_backup_at'][:16].replace('T', ' ')}."))
    else:
        out.append(_item("backups", "Backups", "warn", "Nenhum backup ainda.",
                         "O backup diário é criado automaticamente com o backend rodando."))

    # App (build)
    built = (Path(current_app.config["FRONTEND_DIST"]) / "index.html").is_file()
    out.append(_item("frontend", "App (PWA)", "ok" if built else "warn",
                     "Build encontrado — app em http://localhost:5000." if built else "Build do app não encontrado.",
                     None if built else "Rode 'npm run build' na pasta frontend."))

    # Monitoramento
    last = db.session.scalar(db.select(MonitorRun).order_by(MonitorRun.started_at.desc()).limit(1))
    interval = cfg["check_interval_minutes"]
    if include_scheduler:
        st = scheduler.status()
        if not st["scheduler_active"]:
            out.append(_item("scheduler", "Agendador", "error", "Parado.",
                             "Inicie o backend com 'python run.py' (ou scripts\\iniciar-backend.bat)."))
        elif st["paused"] or not cfg["monitor_enabled"]:
            out.append(_item("scheduler", "Agendador", "warn", "Monitoramento pausado.", "Ative em Sistema."))
        else:
            out.append(_item("scheduler", "Agendador", "ok", f"Ativo, a cada {interval} min."))
    if last is None:
        out.append(_item("last_run", "Última verificação", "warn", "Nenhuma verificação ainda."))
    else:
        age = now - (last.finished_at or last.started_at)
        late = age > timedelta(minutes=interval * 2 + 10) and cfg["monitor_enabled"]
        status = "error" if last.status == "failed" and last.error and "Interrompida" not in last.error else (
            "warn" if late or last.offers_failed else "ok")
        detail = (f"{last.status} há {int(age.total_seconds() // 60)} min — {last.offers_ok}/{last.offers_checked} "
                  f"ok, {last.offers_failed} falha(s), {last.offers_skipped} pulada(s).")
        hint = "O PC pode ter ficado desligado; a retomada é automática ao religar." if late else None
        out.append(_item("last_run", "Última verificação", status, detail, hint))

    # Lojas
    for key, info in STORES.items():
        rows = db.session.execute(
            db.select(Offer.last_status, func.count()).where(Offer.store == key).group_by(Offer.last_status)
        ).all()
        if not rows:
            continue
        by = {s or "pending": n for s, n in rows}
        total, ok = sum(by.values()), by.get("ok", 0)
        status = "ok" if ok == total else "warn"
        detail = f"{ok}/{total} oferta(s) consultadas com sucesso"
        extra = [f"{n} {k}" for k, n in by.items() if k != "ok"]
        out.append(_item(f"store_{key}", info["name"], status, detail + (f" ({', '.join(extra)})" if extra else "") + ".",
                         "Lojas que bloqueiam consultas aceitam preço manual (veja Integrações)." if extra else None))

    # Notificações
    ready = notify.ready_channels()
    pending = db.session.scalar(db.select(func.count(PriceEvent.id)).where(PriceEvent.notified.is_(False))) or 0
    failures = db.session.scalar(db.select(func.count(NotificationLog.id)).where(
        NotificationLog.delivered.is_(False), NotificationLog.created_at >= now - timedelta(days=1))) or 0
    if not ready:
        out.append(_item("notifications", "Alertas no celular", "warn", "Nenhum canal configurado.",
                         "Configure Telegram, ntfy ou Web Push em Alertas."))
    else:
        names = {"telegram": "Telegram", "ntfy": "ntfy", "webpush": f"Web Push ({webpush.count()} aparelho(s))"}
        status = "warn" if failures else "ok"
        out.append(_item("notifications", "Alertas no celular", status,
                         f"Canais: {', '.join(names[c] for c in ready)}; {pending} pendente(s); "
                         f"{failures} falha(s) nas últimas 24 h.",
                         "Veja o histórico em Alertas." if failures else None))

    # Segurança
    host = current_app.config["HOST"]
    if host not in ("127.0.0.1", "localhost") and not current_app.config["API_ACCESS_KEY"]:
        out.append(_item("security", "Segurança", "error",
                         f"API escutando em {host} sem chave de acesso.",
                         "Volte HOST=127.0.0.1 (use o Tailscale Serve) ou defina API_ACCESS_KEY no .env."))
    else:
        out.append(_item("security", "Segurança", "ok",
                         f"API em {host}" + (" com chave de acesso." if current_app.config["API_ACCESS_KEY"] else
                                             " (somente este computador).")))
    return out
