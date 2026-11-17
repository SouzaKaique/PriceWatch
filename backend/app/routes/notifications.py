"""Notificações: canais, teste, histórico."""
from flask import Blueprint, jsonify, request

from ..extensions import db
from ..models import NotificationLog, PriceEvent
from ..services import notify, webpush
from ..services import settings as settings_svc

bp = Blueprint("notifications", __name__)


def _status() -> dict:
    cfg = settings_svc.get_all()
    pending = db.session.scalar(
        db.select(db.func.count(PriceEvent.id)).where(PriceEvent.notified.is_(False))
    ) or 0
    return {
        "channels": notify.channels_status(),
        "pending": pending,
        "quiet_now": notify.in_quiet_hours(cfg),
        "settings": {k: v for k, v in cfg.items() if k.startswith("notify_")},
    }


@bp.get("/notifications/status")
def status():
    return jsonify(_status())


@bp.post("/notifications/telegram/connect")
def telegram_connect():
    try:
        info = notify.telegram_connect()
    except notify.SendError as err:
        return jsonify({"error": "telegram", "message": str(err)}), 400
    return jsonify({**info, **_status()})


@bp.post("/notifications/telegram/disconnect")
def telegram_disconnect():
    notify._set_setting("notify.telegram_chat_id", None)
    db.session.commit()
    return jsonify(_status())


@bp.post("/notifications/test")
def test():
    if not notify.ready_channels():
        return jsonify({"error": "no_channel", "message": "Configure o Telegram ou o ntfy primeiro."}), 400
    return jsonify({"results": notify.send_test()})


@bp.post("/notifications/dispatch")
def dispatch():
    """Envia agora os alertas pendentes (respeitando silêncio, limites e preferências)."""
    return jsonify(notify.dispatch_pending())


@bp.get("/notifications/log")
def log_list():
    limit = min(max(request.args.get("limit", 30, type=int), 1), 200)
    rows = db.session.scalars(
        db.select(NotificationLog).order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc()).limit(limit)
    )
    return jsonify([r.to_dict() for r in rows])


@bp.get("/push/key")
def push_key():
    return jsonify({"public_key": webpush.public_key()})


@bp.post("/push/subscribe")
def push_subscribe():
    try:
        webpush.subscribe(request.get_json(silent=True) or {}, request.headers.get("User-Agent"))
    except webpush.PushError as err:
        return jsonify({"error": "validation", "message": str(err)}), 422
    return jsonify(_status()), 201


@bp.post("/push/unsubscribe")
def push_unsubscribe():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if isinstance(endpoint, str):
        webpush.unsubscribe(endpoint)
    return jsonify(_status())
