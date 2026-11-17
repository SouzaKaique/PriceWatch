"""Estrutura comum a todos os adaptadores de loja."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field


@dataclass
class ProductData:
    """Dados padronizados de um produto em uma loja, obtidos de uma consulta real."""

    store: str
    url: str
    store_product_id: str | None = None
    name: str | None = None
    brand: str | None = None
    model: str | None = None
    mpn: str | None = None  # código do fabricante
    gtin: str | None = None  # EAN
    category: str | None = None
    image_url: str | None = None
    price_cents: int | None = None
    list_price_cents: int | None = None  # preço "de" anunciado
    installment_price_cents: int | None = None  # preço a prazo, se diferente
    available: bool | None = None
    variations: list[str] = field(default_factory=list)
    source: str = ""  # de onde vieram os dados (ex.: "dados estruturados da página")

    def to_dict(self) -> dict:
        return asdict(self)


class LookupFailed(Exception):
    """Falha ao consultar uma loja. `code` é exibido ao usuário de forma clara."""

    CODES = {"blocked", "not_found", "network", "parse", "rate_limited", "unsupported"}

    def __init__(self, code: str, message: str):
        assert code in self.CODES, code
        super().__init__(message)
        self.code = code
        self.message = message


class BaseAdapter:
    key: str = ""
    name: str = ""

    def extract_id(self, url: str) -> str | None:
        """Identificador do produto na loja, extraído da URL (quando possível)."""
        return None

    def canonical_url(self, url: str) -> str:
        """URL sem parâmetros de rastreamento, usada para cache e deduplicação."""
        return re.sub(r"[?#].*$", "", url.strip())

    def fetch(self, url: str) -> ProductData:  # pragma: no cover - interface
        raise NotImplementedError


MODEL_SUFFIX = re.compile(r"\s[-–]\s*([A-Z0-9][A-Z0-9./-]{3,})\s*$", re.I)


def guess_model_from_title(title: str | None) -> str | None:
    """Muitas lojas terminam o título com o modelo: "Monitor LG 24\" ... - 24MS500-B"."""
    if not title:
        return None
    m = MODEL_SUFFIX.search(title)
    if m and any(c.isdigit() for c in m.group(1)):
        return m.group(1).upper()
    return None
