"""Execução do monitoramento: consulta todas as ofertas ativas e registra eventos.

Cada oferta é gravada assim que consultada, então uma execução interrompida
(PC desligado, backend fechado) não perde o que já foi coletado.
"""
from __future__ import annotations

import logging
import threading

from ..adapters.http import blocked_remaining
from ..extensions import db
from ..models import MonitorRun, Offer, Product, utcnow
from . import lookup as lookup_svc
from . import settings as settings_svc
from .events import (
    OfferSnapshot,
    ProductSnapshot,
    detect_analysis_events,
    detect_offer_events,
    detect_product_events,
)

log = logging.getLogger(__name__)
_run_lock = threading.Lock()


def is_running() -> bool:
    return _run_lock.locked()


def check_offer_with_events(offer: Offer, cfg: dict | None = None, use_cache: bool = False) -> tuple[bool, int]:
    """Consulta uma oferta e registra eventos. Retorna (sucesso, nº de eventos)."""
    cfg = cfg or settings_svc.get_all()
    product = offer.product
    p_before = ProductSnapshot.of(product)
    o_before = OfferSnapshot.of(offer)
    ok = lookup_svc.check_offer(offer, use_cache=use_cache)
    events = []
    if ok:
        events += detect_offer_events(product, offer, o_before, cfg)
        events += detect_product_events(product, p_before)
        events += detect_analysis_events(product, offer)
    return ok, len(events)


def run_monitor(reason: str = "scheduled") -> MonitorRun | None:
    """Executa uma rodada completa. Retorna None se já houver uma em andamento."""
    if not _run_lock.acquire(blocking=False):
        log.info("Monitoramento já em execução; pedido '%s' ignorado.", reason)
        return None
    try:
        run = MonitorRun(reason=reason, status="running")
        db.session.add(run)
        db.session.commit()
        cfg = settings_svc.get_all()
        log.info("Monitoramento iniciado (%s).", reason)

        # Cupons oficiais (no máximo a cada 6 h; falhas não interrompem a rodada)
        try:
            from . import coupons as coupons_svc

            res = coupons_svc.refresh_official()
            run.events += res.get("events", 0)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao atualizar cupons")
            db.session.rollback()
            run = db.session.get(MonitorRun, run.id)

        product_ids = db.session.scalars(db.select(Product.id).where(Product.active.is_(True))).all()
        for pid in product_ids:
            product = db.session.get(Product, pid)
            if product is None or not product.active:
                continue
            for offer in list(product.offers):
                if blocked_remaining(offer.url):
                    run.offers_skipped += 1  # loja em pausa após bloqueio: não insistir
                    continue
                run.offers_checked += 1
                try:
                    ok, n = check_offer_with_events(offer, cfg)
                except Exception:  # noqa: BLE001 - uma oferta não pode derrubar a rodada
                    log.exception("Erro inesperado ao consultar oferta %s", offer.id)
                    db.session.rollback()
                    run = db.session.get(MonitorRun, run.id)
                    run.offers_failed += 1
                    db.session.commit()
                    continue
                run.offers_ok += ok
                run.offers_failed += not ok
                run.events += n
                db.session.commit()

        run.status = "done"
        run.finished_at = utcnow()
        db.session.commit()

        try:
            from .notify import dispatch_pending

            dispatch_pending()
        except Exception:  # noqa: BLE001 - falha de envio não invalida a rodada
            log.exception("Falha ao enviar notificações")
            db.session.rollback()
            run = db.session.get(MonitorRun, run.id)
        log.info(
            "Monitoramento concluído: %s consultadas, %s ok, %s falhas, %s puladas, %s eventos.",
            run.offers_checked, run.offers_ok, run.offers_failed, run.offers_skipped, run.events,
        )
        return run
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha no monitoramento")
        db.session.rollback()
        failed = db.session.get(MonitorRun, run.id) if "run" in locals() and run.id else None
        if failed:
            failed.status = "failed"
            failed.error = str(exc)[:500]
            failed.finished_at = utcnow()
            db.session.commit()
        return failed
    finally:
        _run_lock.release()


def last_finished_run() -> MonitorRun | None:
    return db.session.scalar(
        # só rodadas concluídas: uma interrompida (PC desligado) não conta como "verificado"
        db.select(MonitorRun)
        .where(MonitorRun.status == "done", MonitorRun.finished_at.is_not(None))
        .order_by(MonitorRun.finished_at.desc())
        .limit(1)
    )


def close_interrupted_runs() -> None:
    """Rodadas que ficaram 'running' porque o backend foi encerrado no meio."""
    for run in db.session.scalars(db.select(MonitorRun).where(MonitorRun.status == "running")):
        run.status = "failed"
        run.error = "Interrompida (backend encerrado durante a execução)."
        run.finished_at = run.finished_at or utcnow()
    db.session.commit()
