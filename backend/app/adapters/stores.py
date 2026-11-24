"""Adaptadores das lojas — todos implementam `fetch(url) -> ProductData`.

Fonte de dados por loja (situação verificada em 17/11/2026):

- KaBuM!: dados estruturados publicados na página (JSON-LD + dados da página).
  Traz preço à vista, preço a prazo e preço "de".
- Mercado Livre: API oficial (api.mercadolibre.com) com credenciais de um app
  gratuito do próprio usuário. Sem credenciais, tenta os dados da página
  (que costumam cair em verificação anti-robô).
- Amazon: a PA-API 5 foi aposentada em 2026; a substituta (Creators API) exige
  conta de Associados com vendas recentes — inviável para uso pessoal. Tenta os
  dados da página; quando bloqueada, informa e aceita preço manual.
- Pichau: sem API pública; a página responde 403 a clientes automatizados.
  Informa e aceita preço manual.

Quando a loja bloqueia, o adaptador informa a limitação e nada é inventado.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .base import BaseAdapter, LookupFailed, ProductData, guess_model_from_title
from .http import get_html, get_json
from .structured import extract, parse_price


class StructuredDataAdapter(BaseAdapter):
    method = "Dados estruturados publicados na página do produto"
    official_api = False

    def fetch(self, url: str) -> ProductData:
        html, final_url = get_html(url, self.name)
        fields = extract(html)
        if not fields.get("name") and fields.get("price_cents") is None:
            raise LookupFailed(
                "parse",
                f"A página da {self.name} não trouxe dados de produto reconhecíveis. "
                "Confira o link ou preencha manualmente.",
            )
        data = ProductData(
            store=self.key,
            url=self.canonical_url(final_url or url),
            store_product_id=self.extract_id(final_url or url) or fields.get("sku"),
            name=fields.get("name"),
            brand=fields.get("brand"),
            model=fields.get("model") or guess_model_from_title(fields.get("name")),
            mpn=fields.get("mpn"),
            gtin=fields.get("gtin"),
            category=fields.get("category"),
            image_url=fields.get("image_url"),
            price_cents=fields.get("price_cents"),
            available=fields.get("available"),
            variations=fields.get("variations", []),
            source="dados estruturados publicados na página da loja",
        )
        return self.post_process(data, html)

    def post_process(self, data: ProductData, html: str) -> ProductData:
        return data


class KaBuMAdapter(StructuredDataAdapter):
    key, name = "kabum", "KaBuM!"
    _id = re.compile(r"/produto/(\d+)")

    def extract_id(self, url: str) -> str | None:
        m = self._id.search(url)
        return m.group(1) if m else None

    def canonical_url(self, url: str) -> str:
        pid = self.extract_id(url)
        return f"https://www.kabum.com.br/produto/{pid}" if pid else super().canonical_url(url)

    def post_process(self, data: ProductData, html: str) -> ProductData:
        """A página também traz preço "de", preço a prazo e preço à vista."""
        tag = BeautifulSoup(html, "html.parser").find("script", id="__NEXT_DATA__")
        try:
            product = json.loads(tag.string)["props"]["pageProps"]["product"]
        except (AttributeError, TypeError, KeyError, ValueError):
            return data
        prices = product.get("prices") or {}
        cash = parse_price(prices.get("priceWithDiscount"))
        regular = parse_price(prices.get("price"))
        old = parse_price(prices.get("oldPrice"))
        if cash:
            data.price_cents = cash
        best = data.price_cents
        if regular and best and regular > best:
            data.installment_price_cents = regular
        if old and best and old > max(best, regular or 0):
            data.list_price_cents = old
        if isinstance(product.get("available"), bool):
            data.available = product["available"]
        data.source = "dados publicados na página da KaBuM! (preço à vista)"
        return data


class PichauAdapter(StructuredDataAdapter):
    key, name = "pichau", "Pichau"
    limitation = (
        "A Pichau não oferece API pública e bloqueia consultas automatizadas (HTTP 403). "
        "Registre o preço manualmente quando quiser acompanhar."
    )


class AmazonAdapter(StructuredDataAdapter):
    key, name = "amazon", "Amazon Brasil"
    _asin = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})", re.I)
    limitation = (
        "A API oficial da Amazon (Creators API, sucessora da PA-API 5) exige conta de "
        "Associados com vendas recentes. A página bloqueia consultas automatizadas. "
        "Registre o preço manualmente quando quiser acompanhar."
    )

    def extract_id(self, url: str) -> str | None:
        m = self._asin.search(url)
        return m.group(1).upper() if m else None

    def canonical_url(self, url: str) -> str:
        asin = self.extract_id(url)
        return f"https://www.amazon.com.br/dp/{asin}" if asin else super().canonical_url(url)


class MercadoLivreAdapter(StructuredDataAdapter):
    """Usa a API oficial quando há credenciais; senão, os dados da página."""

    key, name = "mercadolivre", "Mercado Livre"
    API = "https://api.mercadolibre.com"
    _item = re.compile(r"(?<![A-Z])MLB-?(\d{6,})", re.I)
    _catalog = re.compile(r"/p/(MLB\d{5,})", re.I)
    _wid = re.compile(r"[?&#](?:wid|item_id)=(MLB\d{6,})", re.I)
    # links de "produto do usuário" (/up/MLBU…) trazem o anúncio só em pdp_filters=item_id:MLB…
    _pdp = re.compile(r"item_id(?:%3A|:)(MLB\d{6,})", re.I)
    _categories: dict[str, str] = {}

    @property
    def method(self) -> str:  # type: ignore[override]
        from ..services import ml_auth

        return "API oficial do Mercado Livre" if ml_auth.is_configured() else super().method

    def ids(self, url: str) -> tuple[str | None, str | None]:
        """(item_id, catalog_product_id) presentes na URL."""
        wid = self._wid.search(url)
        cat = self._catalog.search(url)
        item = None
        if wid:
            item = wid.group(1).upper()
        elif not cat:
            m = self._item.search(url)
            if m:
                item = f"MLB{m.group(1)}"
            else:
                pdp = self._pdp.search(url)
                item = pdp.group(1).upper() if pdp else None
        return item, (cat.group(1).upper() if cat else None)

    def extract_id(self, url: str) -> str | None:
        item, catalog = self.ids(url)
        return item or catalog

    def canonical_url(self, url: str) -> str:
        base = re.sub(r"[?#].*$", "", url.strip())
        item = self.ids(url)[0]
        keep = self._catalog.search(url) and self._wid.search(url)
        # sem código no caminho (ex.: /up/MLBU…): guarda o anúncio para não perdê-lo
        keep = keep or (item and not self._catalog.search(base) and not self._item.search(base))
        return base + (f"?wid={item}" if keep else "")

    # ---- API oficial --------------------------------------------------------

    def _api(self, path: str, params: dict | None = None):
        from ..services import ml_auth

        for attempt in (0, 1):
            token = ml_auth.access_token(force_refresh=attempt == 1)
            status, body = get_json(
                f"{self.API}{path}", self.name, headers={"Authorization": f"Bearer {token}"}, params=params
            )
            if status == 401 and attempt == 0:
                continue  # token expirado: renova e tenta de novo
            break
        if status == 404:
            raise LookupFailed("not_found", "Anúncio/produto não encontrado no Mercado Livre.")
        if status in (401, 403):
            mode = ml_auth.status().get("mode")
            hint = (
                " O token de aplicação pode não ter acesso a este recurso — autorize sua conta "
                "na página Integrações."
                if mode == "app"
                else ""
            )
            msg = f"A API do Mercado Livre negou acesso (HTTP {status}).{hint}"
            ml_auth.record_error(msg)
            raise LookupFailed("blocked", msg)
        if status >= 400 or body is None:
            raise LookupFailed("network", f"A API do Mercado Livre respondeu com erro HTTP {status}.")
        return body

    def _category_name(self, category_id: str | None) -> str | None:
        if not category_id:
            return None
        if category_id not in self._categories:
            try:
                body = self._api(f"/categories/{category_id}")
                self._categories[category_id] = body.get("name")
            except LookupFailed:
                return None
        return self._categories.get(category_id)

    @staticmethod
    def _attrs(attributes) -> dict[str, str]:
        out = {}
        for a in attributes or []:
            if isinstance(a, dict) and a.get("id") and a.get("value_name"):
                out[a["id"]] = a["value_name"]
        return out

    def _from_item(self, item: dict, url: str) -> ProductData:
        if item.get("currency_id") not in (None, "BRL"):
            raise LookupFailed("parse", "Anúncio em moeda diferente de BRL.")
        attrs = self._attrs(item.get("attributes"))
        price = parse_price(item.get("price"))
        original = parse_price(item.get("original_price"))
        status = item.get("status")
        qty = item.get("available_quantity")
        available = status == "active" and (qty is None or qty > 0) if status else None
        pics = item.get("pictures") or []
        image = (pics[0].get("secure_url") or pics[0].get("url")) if pics else item.get("secure_thumbnail")
        title = item.get("title")
        return ProductData(
            store=self.key,
            url=item.get("permalink") or self.canonical_url(url),
            store_product_id=item.get("id"),
            name=title,
            brand=attrs.get("BRAND"),
            model=attrs.get("MODEL") or guess_model_from_title(title),
            mpn=attrs.get("PART_NUMBER") or attrs.get("MPN"),
            gtin=attrs.get("GTIN"),
            category=self._category_name(item.get("category_id")),
            image_url=image,
            price_cents=price,
            list_price_cents=original if original and price and original > price else None,
            available=available,
            source="API oficial do Mercado Livre",
        )

    def _from_catalog(self, product_id: str, url: str) -> ProductData:
        prod = self._api(f"/products/{product_id}")
        attrs = self._attrs(prod.get("attributes"))
        winner = prod.get("buy_box_winner") or {}
        price = parse_price(winner.get("price"))
        original = parse_price(winner.get("original_price"))
        if price is None:
            # Sem vencedor da buy box: menor preço entre os anúncios do produto.
            try:
                listing = self._api(f"/products/{product_id}/items")
                results = [r for r in (listing.get("results") or []) if parse_price(r.get("price"))]
                if results:
                    best = min(results, key=lambda r: parse_price(r.get("price")))
                    price, original = parse_price(best.get("price")), parse_price(best.get("original_price"))
            except LookupFailed:
                pass
        pics = prod.get("pictures") or []
        status = prod.get("status")
        return ProductData(
            store=self.key,
            url=self.canonical_url(url),
            store_product_id=product_id,
            name=prod.get("name"),
            brand=attrs.get("BRAND"),
            model=attrs.get("MODEL") or guess_model_from_title(prod.get("name")),
            mpn=attrs.get("PART_NUMBER") or attrs.get("MPN"),
            gtin=attrs.get("GTIN"),
            category=None,  # produtos de catálogo não trazem category_id
            image_url=pics[0].get("url") if pics else None,
            price_cents=price,
            list_price_cents=original if original and price and original > price else None,
            available=(price is not None) if status in (None, "active") else False,
            source="API oficial do Mercado Livre (catálogo)",
        )

    def fetch(self, url: str) -> ProductData:
        from ..services import ml_auth

        if not ml_auth.is_configured():
            return super().fetch(url)
        item_id, catalog_id = self.ids(url)
        if item_id:
            return self._from_item(self._api(f"/items/{item_id}"), url)
        if catalog_id:
            return self._from_catalog(catalog_id, url)
        raise LookupFailed("parse", "Não encontrei o código do anúncio (MLB…) no link.")


ADAPTERS: dict[str, BaseAdapter] = {
    a.key: a for a in (KaBuMAdapter(), PichauAdapter(), MercadoLivreAdapter(), AmazonAdapter())
}


def get_adapter(store: str | None) -> BaseAdapter | None:
    return ADAPTERS.get(store or "")
