"""Agendamento local do monitoramento (APScheduler, dentro do processo do backend).

- Roda enquanto o backend estiver em execução no computador.
- Ao iniciar, se a última rodada for mais antiga que o intervalo (ex.: o PC ficou
  desligado), agenda uma rodada de retomada 1 minuto depois.
- Nunca roda duas rodadas ao mesmo tempo.
"""
from __future__ import annotations

import atexit
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask

from .extensions import db
from .services import monitor as monitor_svc
from .services import settings as settings_svc

log = logging.getLogger(__name__)
JOB_ID = "monitor"
STARTUP_DELAY_SECONDS = 60

_scheduler: BackgroundScheduler | None = None
_app: Flask | None = None
_startup_pending = False


def _job(reason: str | None = None) -> None:
    global _startup_pending
    assert _app is not None
    if reason is None:
        reason = "startup" if _startup_pending else "scheduled"
        _startup_pending = False
    with _app.app_context():
        try:
            if reason == "startup":
                last = monitor_svc.last_finished_run()
                interval = settings_svc.get("check_interval_minutes")
                if last and last.finished_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(
                    minutes=interval / 2
                ):
                    log.info("Retomada dispensada: houve uma verificação recente.")
                    return
            monitor_svc.run_monitor(reason)
        finally:
            db.session.remove()


def _flush_notifications() -> None:
    """Alertas retidos (horário de silêncio, limite por hora, falha de rede) saem aqui."""
    assert _app is not None
    from .services.notify import dispatch_pending

    with _app.app_context():
        try:
            dispatch_pending()
        finally:
            db.session.remove()


def _maintenance() -> None:
    """Backup diário do banco (o próprio serviço evita backups repetidos)."""
    assert _app is not None
    from .services import maintenance

    with _app.app_context():
        try:
            maintenance.backup()
        except Exception:  # noqa: BLE001
            log.exception("Falha no backup do banco")
        finally:
            db.session.remove()


def _first_run_at(interval_min: int) -> tuple[datetime, str]:
    now = datetime.now(timezone.utc)
    last = monitor_svc.last_finished_run()
    if last is None:
        return now + timedelta(seconds=STARTUP_DELAY_SECONDS), "startup"
    due = last.finished_at.replace(tzinfo=timezone.utc) + timedelta(minutes=interval_min)
    if due <= now:
        return now + timedelta(seconds=STARTUP_DELAY_SECONDS), "startup"
    return due, "scheduled"


def start(app: Flask) -> None:
    global _scheduler, _app, _startup_pending
    if _scheduler is not None:
        return
    _app = app
    with app.app_context():
        monitor_svc.close_interrupted_runs()
        cfg = settings_svc.get_all()
        first, reason = _first_run_at(cfg["check_interval_minutes"])
    _startup_pending = reason == "startup"

    _scheduler = BackgroundScheduler(timezone=timezone.utc, job_defaults={"coalesce": True, "max_instances": 1})
    _scheduler.add_job(
        _job,
        "interval",
        minutes=cfg["check_interval_minutes"],
        next_run_time=first,
        id=JOB_ID,
        misfire_grace_time=None,  # PC acordou após suspensão longa: roda a rodada atrasada (uma vez)
    )
    _scheduler.add_job(_flush_notifications, "interval", minutes=10, id="notify-flush", misfire_grace_time=None)
    _scheduler.add_job(_maintenance, "interval", hours=6, id="maintenance", misfire_grace_time=None,
                       next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2))
    _scheduler.start()
    if not cfg["monitor_enabled"]:
        _scheduler.pause_job(JOB_ID)
    atexit.register(lambda: _scheduler and _scheduler.shutdown(wait=False))
    log.info(
        "Agendador iniciado: a cada %s min; próxima rodada %s (%s).",
        cfg["check_interval_minutes"], first.isoformat(), reason,
    )


def apply_settings(cfg: dict) -> None:
    """Aplica intervalo/ativação após o usuário alterar as configurações."""
    if _scheduler is None:
        return
    job = _scheduler.get_job(JOB_ID)
    if job is None:
        return
    if job.trigger.interval != timedelta(minutes=cfg["check_interval_minutes"]):
        pending = job.next_run_time
        _scheduler.reschedule_job(JOB_ID, trigger="interval", minutes=cfg["check_interval_minutes"])
        new_next = _scheduler.get_job(JOB_ID).next_run_time
        if pending and new_next and pending < new_next:
            _scheduler.modify_job(JOB_ID, next_run_time=pending)  # não perde a rodada que estava próxima
    paused = _scheduler.get_job(JOB_ID).next_run_time is None
    if cfg["monitor_enabled"] and paused:
        _scheduler.resume_job(JOB_ID)  # recalcula a próxima rodada a partir de agora
    elif not cfg["monitor_enabled"] and not paused:
        _scheduler.pause_job(JOB_ID)


def run_now() -> bool:
    """Dispara uma rodada imediata. False se já houver uma em andamento.

    Com o agendador ativo, roda em segundo plano; sem ele (testes), roda na hora.
    """
    if monitor_svc.is_running():
        return False
    if _scheduler is not None:
        _scheduler.add_job(_job, "date", run_date=datetime.now(timezone.utc), kwargs={"reason": "manual"})
        return True
    return monitor_svc.run_monitor("manual") is not None


def status() -> dict:
    job = _scheduler.get_job(JOB_ID) if _scheduler else None
    nxt = job.next_run_time if job else None
    return {
        "scheduler_active": bool(_scheduler and _scheduler.running),
        "paused": bool(job and nxt is None),
        "next_run_at": nxt.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z" if nxt else None,
        "running": monitor_svc.is_running(),
    }
