"""Notificações no celular.

Canais gratuitos, sem cartão e sem hospedagem (o backend local só faz requisições
de saída — funciona com o celular em qualquer lugar):

- Telegram: bot criado por você no @BotFather (TELEGRAM_BOT_TOKEN no .env). O chat é
  detectado depois que você manda /start para o bot.
- ntfy: app ntfy no celular inscrito num tópico secreto (NTFY_TOPIC no .env). O nome
  do tópico funciona como senha no servidor público ntfy.sh.

- Web Push: notificação do próprio PWA instalado (exige acesso por HTTPS no celular,
  ex.: Tailscale Serve — veja o README).

Controles: tipos de alerta escolhidos pelo usuário, horário de silêncio, limite por
hora, deduplicação de 24 h e descarte de alertas antigos (não "despeja" o passado).
"""
from __future__ import annotations

import html
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from ..extensions import db
from ..models import NotificationLog, Offer, PriceEvent, Product, Setting
from ..stores import STORES
from . import settings as settings_svc
from . import webpush

log = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")
TIMEOUT = 15
MAX_EVENT_AGE = timedelta(hours=24)  # alertas mais antigos que isso não são enviados
DEDUPE_WINDOW = timedelta(hours=24)
MAX_ATTEMPTS = 3

_lock = threading.Lock()
_http = requests.Session()

TITLES = {
    "target_reached": "Oportunidade encontrada!",
    "price_drop": "Queda de preço",
    "lowest_ever": "Menor preço registrado",
    "opportunity": "Ótima oportunidade",
    "coupon_available": "Cupom disponível",
    "back_in_stock": "Voltou ao estoque",
    "better_store": "Oferta melhor em outra loja",
    "price_increase": "Aumento de preço",
    "out_of_stock": "Produto indisponível",
    "misleading_promo": "Possível promoção enganosa",
}


class SendError(Exception):
    pass


def brl(c: int | None) -> str:
    if c is None:
        return "—"
    return "R$ " + f"{c / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---- Canais -------------------------------------------------------------------

def _setting(key: str) -> str | None:
    row = db.session.get(Setting, key)
    return row.value if row else None


def _set_setting(key: str, value: str | None) -> None:
    row = db.session.get(Setting, key)
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def telegram_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def telegram_chat_id() -> str | None:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip() or _setting("notify.telegram_chat_id")


def ntfy_topic() -> str:
    return os.getenv("NTFY_TOPIC", "").strip()


def ntfy_server() -> str:
    return os.getenv("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")


def channels_status() -> dict:
    """Situação dos canais — sem expor o token do bot."""
    topic = ntfy_topic()
    return {
        "telegram": {
            "token_configured": bool(telegram_token()),
            "chat_connected": bool(telegram_chat_id()),
            "bot_username": _setting("notify.telegram_bot_username"),
            "ready": bool(telegram_token() and telegram_chat_id()),
        },
        "ntfy": {
            "configured": bool(topic),
            "server": ntfy_server(),
            # o tópico precisa ser digitado no app do celular, então é exibido aqui (só localmente)
            "topic": topic or None,
            "ready": bool(topic),
        },
        "webpush": {"ready": webpush.count() > 0, "devices": webpush.count()},
    }


def _telegram_api(method: str, payload: dict | None = None) -> dict:
    token = telegram_token()
    if not token:
        raise SendError("TELEGRAM_BOT_TOKEN não configurado no .env.")
    try:
        r = _http.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {}, timeout=TIMEOUT)
        body = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise SendError(f"Falha de conexão com o Telegram ({exc.__class__.__name__}).") from exc
    if not body.get("ok"):
        raise SendError(f"Telegram recusou: {body.get('description') or r.status_code}.")
    return body.get("result")


def telegram_connect() -> dict:
    """Detecta o chat a partir da última mensagem enviada ao bot (ex.: /start)."""
    me = _telegram_api("getMe")
    _set_setting("notify.telegram_bot_username", me.get("username"))
    updates = _telegram_api("getUpdates", {"timeout": 0, "allowed_updates": ["message"]}) or []
    chats = [
        u["message"]["chat"]
        for u in updates
        if isinstance(u, dict) and u.get("message", {}).get("chat", {}).get("type") == "private"
    ]
    if not chats:
        db.session.commit()
        raise SendError(f"Nenhuma mensagem encontrada. Abra o Telegram, procure @{me.get('username')} "
                        "e envie /start; depois tente de novo.")
    chat = chats[-1]
    _set_setting("notify.telegram_chat_id", str(chat["id"]))
    db.session.commit()
    return {"chat_name": chat.get("first_name") or chat.get("username"), "bot_username": me.get("username")}


def send_telegram(title: str, body: str, url: str | None) -> None:
    chat = telegram_chat_id()
    if not chat:
        raise SendError("Chat do Telegram não conectado.")
    text = f"<b>PRICE WATCH — {html.escape(title)}</b>\n\n{html.escape(body)}"
    if url:
        text += f'\n\n<a href="{html.escape(url, quote=True)}">Toque para conferir a oferta</a>'
    _telegram_api("sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML",
                                  "disable_web_page_preview": False})


def send_ntfy(title: str, body: str, url: str | None, priority: str = "default") -> None:
    topic = ntfy_topic()
    if not topic:
        raise SendError("NTFY_TOPIC não configurado no .env.")
    payload = {"topic": topic, "title": f"PRICE WATCH — {title}", "message": body,
               "priority": {"high": 4, "default": 3, "low": 2}[priority], "tags": ["shopping_cart"]}
    if url:
        payload["click"] = url
        payload["actions"] = [{"action": "view", "label": "Ver oferta", "url": url}]
    try:
        r = _http.post(ntfy_server(), json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SendError(f"Falha de conexão com o ntfy ({exc.__class__.__name__}).") from exc
    if r.status_code == 429:
        raise SendError("ntfy: limite de envios atingido; tentaremos depois.")
    if r.status_code >= 400:
        raise SendError(f"ntfy respondeu HTTP {r.status_code}.")


def send_webpush(title: str, body: str, url: str | None) -> None:
    try:
        webpush.send(title, body, url)
    except webpush.PushError as err:
        raise SendError(str(err)) from err


CHANNELS = {"telegram": send_telegram, "ntfy": send_ntfy, "webpush": send_webpush}


def ready_channels() -> list[str]:
    st = channels_status()
    return [name for name in CHANNELS if st[name]["ready"]]


# ---- Mensagens ------------------------------------------------------------------

def compose(ev: PriceEvent) -> tuple[str, str, str | None, str]:
    """(título, corpo, link, prioridade). O link abre a oferta original."""
    product = db.session.get(Product, ev.product_id) if ev.product_id else None
    offer = db.session.get(Offer, ev.offer_id) if ev.offer_id else None
    store = STORES.get(ev.store or "", {}).get("name", ev.store or "")
    title = TITLES.get(ev.kind, "Alerta")
    url = offer.url if offer else None
    priority = "high" if ev.kind in ("target_reached", "opportunity", "lowest_ever") else "default"

    if ev.kind == "target_reached" and product:
        body = (f"Seu {product.name} está custando {brl(ev.new_price_cents)} na {store}.\n\n"
                f"Preço desejado: {brl(product.target_price_cents)}.\n\nO preço-alvo foi atingido!")
    else:
        body = ev.message
    if ev.source == "manual":
        body += "\n\n(Preço informado por você.)"
    return title, body, url, priority


# ---- Despacho ----------------------------------------------------------------------

def in_quiet_hours(cfg: dict, now: datetime | None = None) -> bool:
    if not cfg["notify_quiet_enabled"]:
        return False
    local = (now or datetime.now(timezone.utc)).astimezone(TZ).strftime("%H:%M")
    start, end = cfg["notify_quiet_start"], cfg["notify_quiet_end"]
    return (start <= local < end) if start < end else (local >= start or local < end)


def _dedupe_key(ev: PriceEvent) -> str:
    return f"{ev.kind}:{ev.offer_id or ev.product_id}:{ev.new_price_cents}"


def dispatch_pending(now: datetime | None = None) -> dict:
    """Envia os alertas pendentes. Seguro para chamar a qualquer momento."""
    if not _lock.acquire(blocking=False):
        return {"sent": 0, "skipped": 0, "failed": 0, "held": 0, "busy": True}
    try:
        return _dispatch(now)
    finally:
        _lock.release()


def _dispatch(now: datetime | None) -> dict:
    cfg = settings_svc.get_all()
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(tzinfo=None)
    stats = {"sent": 0, "skipped": 0, "failed": 0, "held": 0}
    pending = db.session.scalars(
        db.select(PriceEvent).where(PriceEvent.notified.is_(False)).order_by(PriceEvent.created_at, PriceEvent.id)
    ).all()
    if not pending:
        return stats

    channels = ready_channels()
    if not cfg["notify_enabled"] or not channels:
        # Sem canal configurado: não acumula indefinidamente — envia só alertas recentes depois.
        for ev in pending:
            if now_utc - ev.created_at > MAX_EVENT_AGE:
                ev.notified = True
                stats["skipped"] += 1
        db.session.commit()
        stats["held"] = len(pending) - stats["skipped"]
        return stats

    quiet = in_quiet_hours(cfg, now)
    sent_last_hour = db.session.scalar(
        db.select(db.func.count(db.func.distinct(NotificationLog.event_id))).where(
            NotificationLog.delivered.is_(True), NotificationLog.created_at >= now_utc - timedelta(hours=1)
        )
    ) or 0

    for ev in pending:
        product = db.session.get(Product, ev.product_id) if ev.product_id else None
        if (
            now_utc - ev.created_at > MAX_EVENT_AGE
            or not cfg["notify_kinds"].get(ev.kind, False)
            or (product is not None and not product.active)
        ):
            ev.notified = True  # antigo, tipo desligado ou produto pausado: não envia
            stats["skipped"] += 1
            continue
        key = _dedupe_key(ev)
        dup = db.session.scalar(
            db.select(NotificationLog.id).where(
                NotificationLog.dedupe_key == key,
                NotificationLog.delivered.is_(True),
                NotificationLog.created_at >= now_utc - DEDUPE_WINDOW,
            ).limit(1)
        )
        if dup:
            ev.notified = True
            stats["skipped"] += 1
            continue
        if quiet or sent_last_hour >= cfg["notify_max_per_hour"]:
            stats["held"] += 1  # fica pendente para a próxima rodada
            continue

        title, body, url, priority = compose(ev)
        delivered_any = False
        for ch in channels:
            entry = NotificationLog(kind=ev.kind, product_id=ev.product_id, offer_id=ev.offer_id, event_id=ev.id,
                                    title=title, body=body, url=url, dedupe_key=key, channel=ch)
            try:
                if ch == "ntfy":
                    send_ntfy(title, body, url, priority)
                else:
                    CHANNELS[ch](title, body, url)
                entry.delivered = True
                delivered_any = True
            except SendError as err:
                entry.error = str(err)
                log.warning("Notificação %s via %s falhou: %s", ev.id, ch, err)
            db.session.add(entry)
        db.session.flush()

        attempts = db.session.scalar(
            db.select(db.func.count(NotificationLog.id)).where(NotificationLog.event_id == ev.id)
        ) or 0
        if delivered_any:
            ev.notified = True
            stats["sent"] += 1
            sent_last_hour += 1
        elif attempts >= MAX_ATTEMPTS * len(channels):
            ev.notified = True  # desiste após algumas tentativas (erro fica no histórico)
            stats["failed"] += 1
        else:
            stats["failed"] += 1
        db.session.commit()
    db.session.commit()
    if stats["sent"] or stats["failed"]:
        log.info("Notificações: %s", stats)
    return stats


def send_test() -> dict:
    """Mensagem de teste em todos os canais configurados."""
    results = {}
    for ch in ready_channels():
        try:
            CHANNELS[ch]("Teste de notificação",
                         "Se você está lendo isto no celular, os alertas do PRICE WATCH estão funcionando.",
                         None)
            results[ch] = {"ok": True}
        except SendError as err:
            results[ch] = {"ok": False, "error": str(err)}
        db.session.add(NotificationLog(kind="test", title="Teste de notificação", channel=ch,
                                       delivered=results[ch]["ok"], error=results[ch].get("error")))
    db.session.commit()
    return results


def dispatch_soon() -> None:
    """Dispara o envio em segundo plano (não atrasa a resposta da API).

    Nos testes (TESTING), roda na hora para o resultado ser verificável.
    """
    from flask import current_app

    app = current_app._get_current_object()
    if app.config.get("TESTING"):
        dispatch_pending()
        return

    def run():
        with app.app_context():
            try:
                dispatch_pending()
            except Exception:  # noqa: BLE001
                log.exception("Falha ao enviar notificações")
            finally:
                db.session.remove()

    threading.Thread(target=run, name="notify-dispatch", daemon=True).start()
