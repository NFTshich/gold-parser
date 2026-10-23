# -*- coding: utf-8 -*-
"""Доски объявлений (авитоподобные), которые реально парсятся.

Официальные барахолки (Авито/Мешок/Юла) закрыты антиботом и JS-загрузкой —
проверено: не отдают объявления ни через requests, ни через headless-браузер.
Рабочий аналог — открытые форумы-барахолки радиолюбителей: они отдают
серверный HTML со списком тем (название + часто цена в заголовке) и ссылкой
на объявление. Это и есть «объявления о продаже деталей с драгметаллами».

Сейчас реализован radiokot.ru (phpBB). Топики раздела -> заголовки тем,
в заголовке часто указана цена («Продаю КМ-5 ... за 2000 р»).
Настройки: config.BOARD_FORUMS (id разделов) и BOARD_PAGES.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

import config
import scraper
from reference import Reference

_SID_RE = re.compile(r"&sid=\w+")
_START_RE = re.compile(r"&start=\d+")
_TOPIC_ID_RE = re.compile(r"viewtopic\.php\?t=(\d+)")


class PhpBBAdapter:
    """Парсер phpBB-форума: раздел -> список тем -> лоты из заголовков."""

    name = "board"
    base = ""                       # например https://radiokot.ru
    forum_path = "/forum/viewforum.php"   # ?f=N&start=OFFSET

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(config.HTTP_HEADERS)

    def clean_url(self, url: str) -> str:
        return _START_RE.sub("", _SID_RE.sub("", url or ""))

    def fetch_topics(self, forum_id: int, start: int) -> list[tuple[str, str]]:
        params = f"f={forum_id}"
        if start and start > 0:
            params += f"&start={start}"
        url = f"{self.base}{self.forum_path}?{params}"
        r = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for a in soup.select('a[href*="viewtopic.php?t="]'):
            href = a.get("href", "")
            title = a.get_text(" ", strip=True)
            if not title:
                continue
            tm = _TOPIC_ID_RE.search(href)
            key = tm.group(1) if tm else href
            if key in seen:
                continue
            seen.add(key)
            u = self.clean_url(href)
            if not u.startswith("http"):
                u = self.base.rstrip("/") + "/" + u.lstrip("./")
            out.append((u, title))
        return out

    def scan_forum(self, forum_id: int, pages: int, ref: Reference) -> list[scraper.Lot]:
        lots: list[scraper.Lot] = []
        for off in range(0, pages * 50, 50):
            for url, title in self.fetch_topics(forum_id, off):
                lot = scraper.lot_from_text(title, ref, source=f"{self.name}:f{forum_id}", url=url)
                if lot.price_rub > 0 or lot.parts:
                    lots.append(lot)
        # дедупликация по url
        seen: set[str] = set()
        uniq = []
        for l in lots:
            if l.url and l.url in seen:
                continue
            if l.url:
                seen.add(l.url)
            uniq.append(l)
        return uniq


def scan_boards(forums: list[int] | None = None, pages: int | None = None,
                ref: Reference | None = None, slow: bool = False) -> list[scraper.Lot]:
    from reference import Reference as _R
    ref = ref or _R.load()
    forums = forums or config.BOARD_FORUMS
    pages = pages or config.BOARD_PAGES
    all_lots: list[scraper.Lot] = []

    rk = PhpBBAdapter()
    rk.base = "https://radiokot.ru"
    for f in forums:
        try:
            lots = rk.scan_forum(f, pages, ref)
            print(f"  [radiokot f={f}] тем с ценой/деталью: {len(lots)}")
            all_lots.extend(lots)
        except Exception as exc:
            print(f"  [radiokot f={f}] пропуск: {exc}")

    if slow or config.BOARDS_INCLUDE_SLOW:
        zx = PhpBBAdapter()
        zx.base = "https://zx-pk.com"
        for f in config.ZX_PK_FORUMS:
            try:
                lots = zx.scan_forum(f, pages, ref)
                print(f"  [zx-pk f={f}] тем с ценой/деталью: {len(lots)}")
                all_lots.extend(lots)
            except Exception as exc:
                print(f"  [zx-pk f={f}] пропуск: {exc}")

        v = VkupiAdapter()
        try:
            lots = v.scan_ads(config.ADS_QUERIES, config.ADS_PAGES, ref)
            print(f"  [vkupiprodai] объявлений: {len(lots)}")
            all_lots.extend(lots)
        except Exception as exc:
            print(f"  [vkupiprodai] пропуск: {exc}")

    return all_lots


class VkupiAdapter:
    """Агрегатор объявлений vkupiprodai.ru (без антибота, серверный HTML)."""

    name = "vkupiprodai"
    base = "https://vkupiprodai.ru"

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(config.HTTP_HEADERS)

    def fetch_page(self, query: str, page: int) -> str:
        from urllib.parse import quote
        url = f"{self.base}/search/page{page}/?q={quote(query)}"
        r = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text

    @staticmethod
    def parse_cards(html: str, ref: Reference, source: str) -> list[scraper.Lot]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[scraper.Lot] = []
        for it in soup.select("div.list_item"):
            a = it.select_one("a.list_title")
            if not a:
                continue
            title = a.get_text(" ", strip=True)
            href = a.get("href", "") or ""
            if not href.startswith("http"):
                href = "https://vkupiprodai.ru" + href
            price = 0.0
            p = it.select_one("span.list_price")
            if p:
                from shops import parse_currency
                price = parse_currency(p.get_text(" ", strip=True)) or 0.0
            # заголовок + текст описания как единый текст лота
            txt = it.select_one("p.list_text")
            full = title + (" " + txt.get_text(" ", strip=True) if txt else "")
            if scraper.looks_like_buy_ad(full):
                continue
            lot = scraper.lot_from_text(full, ref, source=source, url=href)
            if price > 0 and lot.price_rub != price:
                lot.price_rub = price
            if lot.price_rub > 0 and not lot.parts:
                continue
            if lot.parts or lot.price_rub > 0:
                out.append(lot)
        return out

    def scan_ads(self, queries: list[str], pages: int, ref: Reference) -> list[scraper.Lot]:
        lots: list[scraper.Lot] = []
        for q in queries:
            for page in range(1, pages + 1):
                try:
                    html = self.fetch_page(q, page)
                    lots.extend(self.parse_cards(html, ref, source=self.name))
                except Exception as exc:
                    print(f"  [vkupiprodai {q} стр.{page}] пропуск: {exc}")
        seen: set[str] = set()
        uniq: list[scraper.Lot] = []
        for l in lots:
            if l.url and l.url in seen:
                continue
            if l.url:
                seen.add(l.url)
            uniq.append(l)
        return uniq