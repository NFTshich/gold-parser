# -*- coding: utf-8 -*-
"""Прайс-листы скупщиков радиодеталей.

Наряду с поиском «что купить дёшево» полезно знать, сколько перекупщики готовы
платить за деталь с драгметаллами (это реалистичная цена «выхода» и калибровка
для справочника). Многие скупщики публикуют каталог с ценами — чистый
серверный HTML.

Структура карточки у Астреи (проверено):
  <div class="js_shop shop-item shop">
     <span class="info"> КМ 5 Н90 зелёные</span>
     <span class="price"><span class="edizm">Цена за кг.</span>..."
        <span class="price_num">120 388,99 руб.</span></span>
     <a class="shop-item-title link" href="...">подробнее</a>

Другие сайты можно добавить, переопределив селекторы в подклассах.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

import config


@dataclass
class ShopItem:
    name: str
    unit: str          # "кг" или "шт"
    price_rub: float
    category: str
    detail_url: str


def parse_currency(text: str) -> float:
    """'120 388,99 руб.' -> 120388.99; '1 560,00  руб.' -> 1560.0"""
    t = re.sub(r"[^\d,]", "", text).replace(" ", "").replace("\u00a0", "")
    t = t.replace(",", ".").strip(".")
    try:
        return float(t)
    except ValueError:
        return 0.0


class ShopParser:
    """Базовый парсер карточек скупщика."""

    name = "shop"
    item_sel = "div.js_shop.shop-item"
    info_sel = "span.info"
    price_num_sel = "span.price_num"
    edizm_sel = "span.edizm"
    detail_sel = "a.shop-item-title"

    def parse(self, html: str, category: str) -> list[ShopItem]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[ShopItem] = []
        for it in soup.select(self.item_sel):
            info = it.select_one(self.info_sel)
            name = info.get_text(" ", strip=True) if info else ""
            pn = it.select_one(self.price_num_sel)
            if not name or not pn:
                continue
            price = parse_currency(pn.get_text(" ", strip=True))
            unit = "шт"
            edz = it.select_one(self.edizm_sel)
            if edz:
                tx = edz.get_text(" ", strip=True).lower()
                unit = "кг" if ("кг" in tx and "шт" not in tx) else "шт"
            link = it.select_one(self.detail_sel)
            detail_url = link.get("href", "") if link else ""
            out.append(ShopItem(name=name, unit=unit, price_rub=price,
                                category=category, detail_url=detail_url))
        return out


def fetch_and_parse(url: str, parser: ShopParser, category: str,
                    session: requests.Session | None = None) -> list[ShopItem]:
    session = session or requests.Session()
    session.headers.update(config.HTTP_HEADERS)
    r = session.get(url, timeout=config.REQUEST_TIMEOUT)
    r.raise_for_status()
    return parser.parse(r.text, category)


def scan_shops(sources: dict[str, str], cat_filter: str | None = None) -> list[ShopItem]:
    """sources: {url: category_name}. Прогоняет все разделы."""
    parser = ShopParser()
    all_items: list[ShopItem] = []
    for url, category in sources.items():
        if cat_filter and cat_filter.lower() not in category.lower():
            continue
        try:
            items = fetch_and_parse(url, parser, category)
            print(f"  [shop] {category}: {len(items)} позиций ({url})")
            all_items.extend(items)
        except Exception as exc:
            print(f"  [shop] {category}: пропуск ({exc})")
    return all_items