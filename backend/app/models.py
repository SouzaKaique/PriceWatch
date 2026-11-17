"""Modelo de dados do PRICE WATCH.

Produto (o que o usuário quer comprar)
 └── Ofertas (o mesmo produto em lojas diferentes)
      └── Histórico de preços (uma linha por consulta efetivamente realizada)

Preços são armazenados em centavos (inteiro) para evitar erros de arredondamento.
"""
from datetime import datetime, timezone

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(300), nullable=False)
    brand = db.Column(db.String(120))
    model = db.Column(db.String(160))
    manufacturer_code = db.Column(db.String(120))  # código do fabricante / part number
    category = db.Column(db.String(120))
    image_url = db.Column(db.String(1000))
    target_price_cents = db.Column(db.Integer)  # preço-alvo
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    offers = db.relationship(
        "Offer", back_populates="product", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self, include_offers: bool = True) -> dict:
        data = {
            "id": self.id,
            "name": self.name,
            "brand": self.brand,
            "model": self.model,
            "manufacturer_code": self.manufacturer_code,
            "category": self.category,
            "image_url": self.image_url,
            "target_price_cents": self.target_price_cents,
            "notes": self.notes,
            "active": self.active,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }
        if include_offers:
            data["offers"] = [o.to_dict() for o in self.offers]
        return data


class Offer(db.Model):
    """Um produto em uma loja específica."""

    __tablename__ = "offers"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    store = db.Column(db.String(40), nullable=False)  # kabum | pichau | mercadolivre | amazon
    url = db.Column(db.String(1500), nullable=False)
    store_product_id = db.Column(db.String(120))  # SKU/ASIN/MLB na loja
    title = db.Column(db.String(400))
    # Dados de identificação obtidos da loja (usados na correspondência entre lojas)
    brand = db.Column(db.String(120))
    model = db.Column(db.String(160))
    mpn = db.Column(db.String(120))
    gtin = db.Column(db.String(40))
    image_url = db.Column(db.String(1000))
    current_price_cents = db.Column(db.Integer)
    previous_price_cents = db.Column(db.Integer)
    list_price_cents = db.Column(db.Integer)  # preço "de" anunciado pela loja
    installment_price_cents = db.Column(db.Integer)  # preço a prazo, quando difere do à vista
    shipping_cents = db.Column(db.Integer)
    # "auto" (consulta à loja) ou "manual" (informado pelo usuário)
    price_source = db.Column(db.String(10))
    # última classificação da análise de preços (para detectar transições)
    last_classification = db.Column(db.String(20))
    available = db.Column(db.Boolean)
    match_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    last_checked_at = db.Column(db.DateTime)
    # ok | error | blocked | not_found | rate_limited | unsupported
    last_status = db.Column(db.String(30))
    last_error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    product = db.relationship("Product", back_populates="offers")
    history = db.relationship(
        "PriceHistory",
        back_populates="offer",
        cascade="all, delete-orphan",
        order_by="(PriceHistory.checked_at, PriceHistory.id)",
        lazy="dynamic",
    )

    __table_args__ = (db.UniqueConstraint("product_id", "url", name="uq_offer_product_url"),)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "product_id": self.product_id,
            "store": self.store,
            "url": self.url,
            "store_product_id": self.store_product_id,
            "title": self.title,
            "brand": self.brand,
            "model": self.model,
            "mpn": self.mpn,
            "gtin": self.gtin,
            "image_url": self.image_url,
            "current_price_cents": self.current_price_cents,
            "previous_price_cents": self.previous_price_cents,
            "list_price_cents": self.list_price_cents,
            "installment_price_cents": self.installment_price_cents,
            "shipping_cents": self.shipping_cents,
            "price_source": self.price_source,
            "available": self.available,
            "match_confirmed": self.match_confirmed,
            "last_checked_at": iso(self.last_checked_at),
            "last_status": self.last_status,
            "last_error": self.last_error,
        }


class PriceHistory(db.Model):
    __tablename__ = "price_history"

    id = db.Column(db.Integer, primary_key=True)
    offer_id = db.Column(
        db.Integer, db.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    price_cents = db.Column(db.Integer)  # nulo quando indisponível
    list_price_cents = db.Column(db.Integer)
    available = db.Column(db.Boolean)
    source = db.Column(db.String(10), default="auto")  # auto | manual
    checked_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    offer = db.relationship("Offer", back_populates="history")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "offer_id": self.offer_id,
            "price_cents": self.price_cents,
            "list_price_cents": self.list_price_cents,
            "available": self.available,
            "source": self.source or "auto",
            "checked_at": iso(self.checked_at),
        }


class Coupon(db.Model):
    """Cupom de desconto. Nunca é afirmado como válido sem confirmação.

    verification_status:
      unconfirmed    – encontrado/cadastrado, condições não testadas no carrinho
      user_confirmed – você testou e funcionou
      user_failed    – você testou e não funcionou
    (expirado/em breve é calculado pelas datas de vigência)
    """

    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    store = db.Column(db.String(40), nullable=False, index=True)
    code = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(400))  # ex.: "em SSD selecionados"
    discount_percent = db.Column(db.Float)
    discount_cents = db.Column(db.Integer)
    max_discount_cents = db.Column(db.Integer)
    min_purchase_cents = db.Column(db.Integer)
    categories = db.Column(db.String(400))
    conditions = db.Column(db.Text)  # texto legal / condições completas
    valid_from = db.Column(db.DateTime)
    valid_until = db.Column(db.DateTime)
    link_url = db.Column(db.String(1500))  # página da promoção/produto indicada pela loja
    source = db.Column(db.String(1000))  # de onde veio a informação
    origin = db.Column(db.String(30), default="manual")  # manual | kabum_official
    external_key = db.Column(db.String(200), index=True)  # para atualizar sem duplicar
    verification_status = db.Column(db.String(20), nullable=False, default="unconfirmed")
    last_seen_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def validity(self, now=None) -> str:
        now = now or utcnow()
        if self.valid_until and self.valid_until < now:
            return "expired"
        if self.valid_from and self.valid_from > now:
            return "upcoming"
        return "active"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "store": self.store,
            "code": self.code,
            "description": self.description,
            "discount_percent": self.discount_percent,
            "discount_cents": self.discount_cents,
            "max_discount_cents": self.max_discount_cents,
            "min_purchase_cents": self.min_purchase_cents,
            "categories": self.categories,
            "conditions": self.conditions,
            "valid_from": iso(self.valid_from),
            "valid_until": iso(self.valid_until),
            "link_url": self.link_url,
            "source": self.source,
            "origin": self.origin or "manual",
            "verification_status": self.verification_status,
            "validity": self.validity(),
            "last_seen_at": iso(self.last_seen_at),
            "created_at": iso(self.created_at),
        }


class Setting(db.Model):
    """Configurações chave/valor (frequência, preferências de notificação etc.)."""

    __tablename__ = "settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text)


class NotificationLog(db.Model):
    """Registro de alertas enviados — usado também para evitar duplicados."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(40), nullable=False)  # price_drop | target_reached | back_in_stock ...
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="SET NULL"))
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id", ondelete="SET NULL"))
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    url = db.Column(db.String(1500))
    dedupe_key = db.Column(db.String(200), index=True)
    event_id = db.Column(db.Integer, db.ForeignKey("price_events.id", ondelete="SET NULL"), index=True)
    channel = db.Column(db.String(20))  # telegram | ntfy | webpush
    delivered = db.Column(db.Boolean, nullable=False, default=False)
    error = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "product_id": self.product_id,
            "offer_id": self.offer_id,
            "title": self.title,
            "body": self.body,
            "url": self.url,
            "event_id": self.event_id,
            "channel": self.channel,
            "delivered": self.delivered,
            "error": self.error,
            "created_at": iso(self.created_at),
        }


class PushSubscription(db.Model):
    """Inscrição Web Push de um dispositivo."""

    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String(1000), nullable=False, unique=True)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    user_agent = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class PriceEvent(db.Model):
    """Mudança relevante detectada pelo monitoramento (base das notificações)."""

    __tablename__ = "price_events"

    id = db.Column(db.Integer, primary_key=True)
    # price_drop | price_increase | back_in_stock | out_of_stock | lowest_ever
    # | target_reached | better_store | opportunity | misleading_promo | coupon_available
    kind = db.Column(db.String(30), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="CASCADE"), index=True)
    offer_id = db.Column(db.Integer, db.ForeignKey("offers.id", ondelete="CASCADE"))
    store = db.Column(db.String(40))
    old_price_cents = db.Column(db.Integer)
    new_price_cents = db.Column(db.Integer)
    message = db.Column(db.String(500), nullable=False)
    source = db.Column(db.String(10), default="auto")  # auto | manual
    notified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "product_id": self.product_id,
            "offer_id": self.offer_id,
            "store": self.store,
            "old_price_cents": self.old_price_cents,
            "new_price_cents": self.new_price_cents,
            "message": self.message,
            "source": self.source or "auto",
            "notified": self.notified,
            "created_at": iso(self.created_at),
        }


class MonitorRun(db.Model):
    """Uma execução do monitoramento (agendada, manual ou de retomada)."""

    __tablename__ = "monitor_runs"

    id = db.Column(db.Integer, primary_key=True)
    reason = db.Column(db.String(20), nullable=False)  # scheduled | manual | startup
    status = db.Column(db.String(20), nullable=False, default="running")  # running | done | failed
    started_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    finished_at = db.Column(db.DateTime)
    offers_checked = db.Column(db.Integer, nullable=False, default=0)
    offers_ok = db.Column(db.Integer, nullable=False, default=0)
    offers_failed = db.Column(db.Integer, nullable=False, default=0)
    offers_skipped = db.Column(db.Integer, nullable=False, default=0)
    events = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "reason": self.reason,
            "status": self.status,
            "started_at": iso(self.started_at),
            "finished_at": iso(self.finished_at),
            "offers_checked": self.offers_checked,
            "offers_ok": self.offers_ok,
            "offers_failed": self.offers_failed,
            "offers_skipped": self.offers_skipped,
            "events": self.events,
            "error": self.error,
        }
