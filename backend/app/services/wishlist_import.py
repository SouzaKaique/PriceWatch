"""Leitura de uma lista de desejos (PDF ou texto colado) para importar produtos.

O que é aproveitado do PDF
- **Links clicáveis** (anotações do PDF): o caso de uma página de favoritos/lista da loja
  "impressa como PDF" pelo navegador — o texto do link vira o nome do produto.
- **Links escritos no texto** (https://...).
- **Linhas com nomes de produtos**, com ou sem preço (ex.: "Monitor LG 27GS60F - R$ 899").
- **Preço visto** perto do produto e **preço-alvo** quando a linha diz "até / alvo / máx".
- **Listas em cartões** (apps de lista de desejos): título com valor, linhas de status
  ("Desejado · Prioridade alta · Adicionado em…"), meta de economia ("Guardado R$ 0 de R$ 300",
  que vira o preço-alvo) e o link logo abaixo, mesmo quando o texto do link é só o endereço.

Somente links de página de produto das lojas suportadas viram ofertas; menus, rodapés,
carrinho e afins são descartados. Nada é cadastrado aqui: o resultado vai para a tela de
revisão, onde você confirma.
"""
from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote, urlparse

from ..adapters import get_adapter
from ..adapters.structured import parse_price
from ..stores import STORES, detect_store
from . import lookup as lookup_svc

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 150
MAX_ITEMS = 300

PRICE_RE = re.compile(r"R\$\s*\d{1,3}(?:\.\d{3})*(?:,\d{2})?|R\$\s*\d+(?:,\d{2})?")
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
TITLE_HINT = re.compile(r"\b(lista de desejos|wishlist|favoritos|minha lista|meus pedidos|carrinho)\b")
FOOTER_HINT = re.compile(
    r"politica de privacidade|termos de uso|todos os direitos|direitos reservados|cnpj|copyright|"
    r"(pagina|page)\s*\d+\s*(de|of|/)\s*\d+"
)
TARGET_HINT = re.compile(r"\b(at[ée]|alvo|m[áa]x(?:imo)?|meta|desejad[oa]|quero por|pagar at[ée])\b", re.I)

# Textos de interface que aparecem em páginas impressas e não são produtos
NOISE_WORDS = [
    "adicionar ao carrinho", "comprar", "comprar agora", "remover", "excluir", "favoritos", "lista de desejos",
    "minha lista", "wishlist", "quantidade", "frete", "ver mais", "ver produto", "compartilhar", "em estoque",
    "indisponivel", "a vista", "no pix", "sem juros", "vendido por", "entregue por", "avise-me", "avaliacoes",
    "mais vendidos", "politica de privacidade", "termos de uso", "fale conosco", "atendimento", "minha conta",
    "entrar", "cadastre-se", "subtotal", "total", "cupom", "desconto", "pagina", "imprimir", "baixar app",
    "valor total", "ja guardado", "guardado", "itens", "onde comprar", "links", "observacoes",
]
# Linhas de status/metadados de apps de lista ("Desejado · Prioridade alta · Adicionado em 12/11/2026")
META_HINT = re.compile(
    r"\b(adicionad[oa]|exportad[oa]|criad[oa]|atualizad[oa]|salv[oa]|incluid[oa])\s+em\s+\d{1,2}/\d{1,2}"
    r"|\bprioridade\s+(alta|media|baixa)\b|^(ja\s+)?guardad[oa]\b|\(\s*\d{1,3}\s*%\s*\)$"
)
SAVINGS_GOAL = re.compile(r"\bguardad[oa]\b.*\bde\b")
NON_PRODUCT_PATHS = {
    "", "carrinho", "cart", "login", "conta", "minha-conta", "favoritos", "lista-de-desejos", "wishlist",
    "busca", "search", "s", "ofertas", "cupons", "hotsite", "promocao", "institucional", "ajuda", "atendimento",
}


@dataclass
class Item:
    name: str
    name_source: str  # link_text | line | url
    urls: list[str] = field(default_factory=list)
    price_seen_cents: int | None = None
    target_price_cents: int | None = None
    line: str = ""
    score: int = 0
    other_links: list[str] = field(default_factory=list)  # links que não são de loja suportada


class ImportError_(Exception):  # noqa: N801 (evita conflito com o builtin ImportError)
    pass


# ---- Utilidades -------------------------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def clean_url(url: str) -> str:
    return url.strip().rstrip(".,;:!?)»”\"'")


def is_product_url(url: str) -> bool:
    """Só páginas de produto das lojas suportadas (descarta menus, carrinho, busca…)."""
    store = detect_store(url)
    if store is None:
        return False
    p = urlparse(url)
    path = p.path.strip("/")
    if store == "kabum":
        return bool(re.match(r"produto/\d+", path))
    if store == "amazon":
        return (p.hostname or "").endswith("amzn.to") or bool(get_adapter("amazon").extract_id(url))
    if store == "mercadolivre":
        return bool(get_adapter("mercadolivre").extract_id(url))
    if store == "pichau":
        first = path.split("/")[0]
        return bool(path) and "/" not in path and first not in NON_PRODUCT_PATHS and path.count("-") >= 3
    return False


def name_from_url(url: str) -> str | None:
    """Nome provisório a partir do endereço (ex.: …/produto/644868/monitor-gamer-lg-24…)."""
    p = urlparse(url)
    parts = [unquote(x) for x in p.path.split("/") if x]
    slug = None
    store = detect_store(url)
    if store == "kabum" and len(parts) >= 3:
        slug = parts[2]
    elif store == "amazon":
        idx = next((i for i, x in enumerate(parts) if x.lower() in ("dp", "gp")), None)
        slug = parts[idx - 1] if idx else None
    elif store == "mercadolivre":
        cand = [x for x in parts if not x.upper().startswith("MLB") and x != "p"]
        slug = cand[0] if cand else re.sub(r"^MLB-?\d+-?", "", parts[-1] if parts else "") or None
        if slug:
            slug = re.sub(r"_JM$", "", slug)
    elif store == "pichau" and parts:
        slug = parts[0]
    if not slug or len(slug) < 4:
        return None
    words = [w for w in re.split(r"[-_+\s]+", slug) if w]
    return " ".join(w if any(c.isdigit() for c in w) and w.isupper() else w.capitalize() for w in words)[:200]


def _is_noise(text: str, priced: bool = False) -> bool:
    """priced=True: a linha tinha um preço junto (ex.: "R$ 600,00Mesa"), então nomes curtos valem."""
    t = _norm(text).strip(" -•·|*")
    if len(t) < (3 if priced else 6) or len(t) > 180:
        return True
    if lookup_svc.looks_like_url(text):
        return True  # texto de link ("kabum.com.br/produto/…") não é nome de produto
    if META_HINT.search(t):
        return True
    if PRICE_RE.fullmatch(text.strip()) or re.fullmatch(r"[\d\s.,/%x-]+", t):
        return True
    if re.fullmatch(r"(pagina|page)?\s*\d+\s*(de|/|of)\s*\d+", t):
        return True
    if re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", t) and len(t) < 30:
        return True
    words = re.findall(r"[a-z0-9]*[a-z][a-z0-9]*", t)  # "g502" conta como palavra
    min_words = 1 if priced else 2
    if len([w for w in words if len(w) >= 2]) < min_words and not (words and any(c.isdigit() for c in t)):
        return True
    if FOOTER_HINT.search(t):
        return True  # rodapés e avisos legais em qualquer parte da linha
    if TITLE_HINT.search(t):
        return True  # títulos/cabeçalhos ("Lista de desejos - Black Friday", "Meus Favoritos")
    # rótulos de interface: iguais ou quase iguais (ex.: "Subtotal:"), sem pegar
    # produtos que só começam com a mesma palavra ("Total War: Warhammer III")
    return any(t == w or (t.startswith(w) and len(t) <= len(w) + 6) for w in NOISE_WORDS)


def _score(name: str, has_price: bool) -> int:
    words = name.split()
    return (2 if has_price else 0) + (len(words) >= 3) + any(c.isdigit() for c in name) + (
        sum(1 for w in words if w[:1].isupper()) >= 2)


def _prices(text: str) -> list[int]:
    return [p for p in (parse_price(m.group(0)) for m in PRICE_RE.finditer(text)) if p]


# ---- PDF ----------------------------------------------------------------------------------

def _pdf_pages(data: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    if len(data) > MAX_BYTES:
        raise ImportError_("O PDF tem mais de 20 MB.")
    if not data.startswith(b"%PDF"):
        raise ImportError_("O arquivo enviado não parece ser um PDF.")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ImportError_("O PDF está protegido por senha.") from exc
        pages = reader.pages
        if len(pages) > MAX_PAGES:
            raise ImportError_(f"O PDF tem {len(pages)} páginas (máximo {MAX_PAGES}).")
        return list(pages)
    except PdfReadError as exc:
        raise ImportError_("Não consegui ler o PDF (arquivo corrompido ou formato não suportado).") from exc


def _page_chunks(page) -> list[tuple[float, float, str]]:
    """Trechos de texto com posição (x, y) na página."""
    chunks: list[tuple[float, float, str]] = []

    def visitor(text, cm, tm, _font, _size):
        if not text or not text.strip():
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        chunks.append((x, y, text))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:  # noqa: BLE001 - PDFs exóticos: segue só com o texto simples
        return []
    return chunks


def _page_links(page) -> list[tuple[str, tuple[float, float, float, float]]]:
    out = []
    for ref in page.get("/Annots") or []:
        try:
            annot = ref.get_object()
            if annot.get("/Subtype") != "/Link":
                continue
            action = annot.get("/A")
            action = action.get_object() if action is not None else None
            if not action or action.get("/S") != "/URI":
                continue
            uri = str(action.get("/URI"))
            x1, y1, x2, y2 = (float(v) for v in annot.get("/Rect"))
            out.append((uri, (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))))
        except Exception:  # noqa: BLE001
            continue
    return out


def _text_in_rect(chunks, rect) -> str:
    x1, y1, x2, y2 = rect
    inside = [(-y, x, t) for x, y, t in chunks if y1 - 3 <= y <= y2 + 3 and x1 - 3 <= x <= x2 + 3]
    inside.sort()
    return re.sub(r"\s+", " ", " ".join(t for _, _, t in inside)).strip()


def _price_near(chunks, rect) -> int | None:
    """Preço mais próximo abaixo/ao lado do link (layout de cartões de produto)."""
    x1, y1, x2, _ = rect
    best = None
    for x, y, t in chunks:
        if not PRICE_RE.search(t):
            continue
        dy = y1 - y  # positivo = abaixo do link
        if -12 <= dy <= 110 and x1 - 30 <= x <= max(x2, x1 + 200) + 30:  # mesma coluna do produto
            dist = abs(dy) + abs(x - x1) / 10
            if best is None or dist < best[0]:
                best = (dist, _prices(t)[0] if _prices(t) else None)
    return best[1] if best else None


def parse_pdf(data: bytes) -> tuple[list[Item], dict]:
    pages = _pdf_pages(data)
    link_items: dict[str, Item] = {}
    link_labels: dict[str, str] = {}  # texto do link que é só o endereço → link completo
    text_parts: list[str] = []
    total_links = 0
    for page in pages:
        chunks = _page_chunks(page)
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            text_parts.append("")
        for uri, rect in _page_links(page):
            total_links += 1
            url = clean_url(uri)
            label = _text_in_rect(chunks, rect)
            if label and lookup_svc.looks_like_url(label):
                link_labels[_norm(label)] = url
            if not is_product_url(url):
                continue
            key = lookup_svc.canonical(url)
            label = PRICE_RE.sub("", label).strip(" -–|·") if label else ""
            good_label = label and not _is_noise(label)
            item = link_items.get(key)
            if item is None:
                item = link_items[key] = Item(name=label if good_label else (name_from_url(url) or ""),
                                              name_source="link_text" if good_label else "url", urls=[url])
            elif good_label and (item.name_source != "link_text" or len(label) > len(item.name)):
                item.name, item.name_source = label, "link_text"
            # o preço vem do link com o nome (o link da imagem fica longe do preço)
            if good_label or item.price_seen_cents is None:
                near = _price_near(chunks, rect)
                if near is not None and (good_label or item.price_seen_cents is None):
                    item.price_seen_cents = near

    text = "\n".join(text_parts)
    known = set(link_items)
    names = {_norm(it.name) for it in link_items.values() if it.name_source == "link_text"}
    consumed: set[str] = set()
    text_items = parse_text(text, skip_urls=known, skip_names=names, link_labels=link_labels, consumed=consumed)
    # links que o texto já juntou ao título do cartão não viram itens separados
    items = [it for key, it in link_items.items() if key not in consumed] + text_items
    stats = {"pages": len(pages), "links": total_links, "product_links": len(link_items),
             "has_text": bool(text.strip())}
    if not stats["has_text"] and not link_items:
        raise ImportError_("Não encontrei texto no PDF — parece ser uma imagem digitalizada. "
                           "Exporte a lista como PDF com texto (ou imprima a página da lista como PDF) "
                           "ou cole os links/nomes no campo de texto.")
    return items, stats


# ---- Texto -----------------------------------------------------------------------------------

def _same_as_known(name: str, known: set[str]) -> bool:
    n = _norm(name)
    return n in known or any(len(n) > 10 and (n in k or k in n) for k in known)


def parse_text(text: str, skip_urls: set[str] | None = None, skip_names: set[str] | None = None,
               link_labels: dict[str, str] | None = None, consumed: set[str] | None = None) -> list[Item]:
    """link_labels: texto de link que é só o endereço → link completo (vindo das anotações do PDF).
    consumed: recebe as URLs canônicas que foram juntadas a um título (não viram item próprio)."""
    skip_urls = skip_urls or set()
    skip_names = skip_names or set()
    link_labels = link_labels or {}
    consumed = consumed if consumed is not None else set()
    items: list[Item] = []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    last_name_item: Item | None = None  # item criado pela linha anterior (para anexar links abaixo do nome)
    prev_was_item_line = False

    for ln in lines:
        if lookup_svc.looks_like_url(ln) and not URL_RE.match(ln):
            # Endereço escrito sem "https://" (texto de link em cartões): pertence ao último título
            url = link_labels.get(_norm(ln)) or "https://" + ln.rstrip(".…")
            if last_name_item is not None:
                if is_product_url(url):
                    if detect_store(url) not in {detect_store(u) for u in last_name_item.urls}:
                        last_name_item.urls.append(url)
                        consumed.add(lookup_svc.canonical(url))
                else:
                    last_name_item.other_links.append(url)
            prev_was_item_line = False
            continue

        urls = [clean_url(u) for u in URL_RE.findall(ln)]
        product_urls = [u for u in urls if is_product_url(u) and lookup_svc.canonical(u) not in skip_urls]
        rest = URL_RE.sub("", ln).strip(" -–|·:")
        prices = _prices(rest)
        name_part = PRICE_RE.sub("", rest).strip(" -–|·:")
        target = prices[0] if prices and TARGET_HINT.search(rest) else None
        seen = prices[0] if prices and target is None else None
        if target is not None:
            name_part = TARGET_HINT.sub("", name_part).strip(" -–|·:")

        if urls and not product_urls:
            prev_was_item_line = False
            continue  # link que não é de produto (ou já veio das anotações)

        priced = bool(prices)
        if last_name_item is not None and prices and SAVINGS_GOAL.search(_norm(rest)):
            # "Guardado R$ 0,00 de R$ 300,00": o valor planejado vira o preço-alvo do item
            if last_name_item.target_price_cents is None:
                last_name_item.target_price_cents = prices[-1]
                if last_name_item.price_seen_cents == prices[-1]:
                    last_name_item.price_seen_cents = None  # era o mesmo valor, não um preço de loja
            continue

        if product_urls and (not name_part or _is_noise(name_part, priced)):
            # Só link(s): junta ao nome logo acima, se for outra loja; senão vira item próprio
            if last_name_item and prev_was_item_line:
                stores_in = {detect_store(u) for u in last_name_item.urls}
                for u in product_urls:
                    if detect_store(u) not in stores_in:
                        last_name_item.urls.append(u)
                        stores_in.add(detect_store(u))
                    else:
                        items.append(Item(name=name_from_url(u) or "", name_source="url", urls=[u], line=ln))
                continue
            for u in product_urls:
                items.append(Item(name=name_from_url(u) or "", name_source="url", urls=[u], line=ln))
            prev_was_item_line = False
            continue

        if name_part and not product_urls and _same_as_known(name_part, skip_names):
            prev_was_item_line = False
            continue  # mesmo produto que já veio de um link clicável

        if not name_part or _is_noise(name_part, priced):
            # linha só com preço: pertence ao item anterior
            if prices and last_name_item and prev_was_item_line and last_name_item.price_seen_cents is None \
                    and last_name_item.target_price_cents is None:
                if target is not None:
                    last_name_item.target_price_cents = target
                else:
                    last_name_item.price_seen_cents = seen
            prev_was_item_line = bool(prices) and prev_was_item_line
            continue

        item = Item(name=name_part[:200], name_source="line", urls=product_urls, price_seen_cents=seen,
                    target_price_cents=target, line=ln)
        item.score = _score(item.name, bool(prices))
        items.append(item)
        last_name_item, prev_was_item_line = item, True

    return items


# ---- Resultado para a tela de revisão --------------------------------------------------

def build_preview(items: list[Item], existing: dict[str, dict], existing_names: set[str] | None = None) -> list[dict]:
    """existing: url canônica → {product_id, name}; existing_names: nomes (normalizados) já cadastrados."""
    existing_names = existing_names or set()
    out, seen_names = [], set()
    for i, it in enumerate(items[:MAX_ITEMS]):
        key_name = _norm(it.name)
        if not it.urls and key_name in seen_names:
            continue
        seen_names.add(key_name)
        urls = []
        for u in dict.fromkeys(it.urls):
            store = detect_store(u)
            canon = lookup_svc.canonical(u, store)
            urls.append({
                "url": canon,
                "store": store,
                "store_name": STORES[store]["name"],
                "existing": existing.get(canon),
            })
        has_link = bool(urls)
        all_existing = has_link and all(u["existing"] for u in urls)
        same_name = not has_link and key_name in existing_names
        checked = (has_link or it.score >= 2 or it.price_seen_cents is not None or it.target_price_cents is not None) \
            and not all_existing and not same_name
        warnings = []
        if same_name:
            warnings.append("Já existe um produto com este nome.")
        if not has_link and not same_name:
            warnings.append("Sem link de loja: cole um link para o produto ser monitorado.")
        if all_existing:
            warnings.append("Já monitorado.")
        for other in dict.fromkeys(it.other_links):
            host = (urlparse(other).hostname or other).removeprefix("www.")
            store = detect_store(other)
            if store:
                warnings.append(f"O link da {STORES[store]['name']} está incompleto no PDF — cole o link completo.")
            elif not has_link:
                warnings.append(f"O link ({host}) não é de uma loja suportada — cole um link da KaBuM!, "
                                "Pichau, Mercado Livre ou Amazon.")
        if it.name_source == "url":
            warnings.append("Nome provisório (tirado do link) — será trocado pelo da loja ao identificar.")
        out.append({
            "key": f"i{i}",
            "name": it.name or (urls[0]["store_name"] + " — produto" if urls else ""),
            "name_source": it.name_source,
            "urls": urls,
            "price_seen_cents": it.price_seen_cents,
            "target_price_cents": it.target_price_cents,
            "line": it.line[:240],
            "checked": checked,
            "warnings": warnings,
        })
    return out
