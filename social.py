# -*- coding: utf-8 -*-
"""Сканирование Telegram по публичным превью каналов.

Как это работает: у любого публичного канала есть web-превью
    https://t.me/s/<username>
которое отдаёт последние сообщения HTML-страницей БЕЗ логина и токена.
Мы парсим её, берём текст сообщений, распознаём цену и тип детали из
справочника — то есть повторяем логику `eval`, но автоматически по каналу.
Источник данных — публичный контент каналов, читать его можно свободно;
бот ничего не постит и не отправляет.

Каналы настраиваются в social_channels.py.
"""

from __future__ import annotations

import os

import requests
from bs4 import BeautifulSoup

import config
import scraper
from reference import Reference

_TME = "https://t.me/s/{username}"


class TelegramAdapter:
    """Парсер публичной страницы канала t.me/s/<username>."""

    name = "telegram"

    def __init__(self, username: str, session: requests.Session | None = None):
        self.username = username
        self.session = session or requests.Session()
        self.session.headers.update(config.HTTP_HEADERS)

    def fetch_page(self) -> str:
        url = _TME.format(username=self.username)
        r = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text

    def parse_messages(self, html: str, max_msgs: int,
                       ref: Reference) -> list[scraper.Lot]:
        """Извлекает из HTML t.me/s список непустых сообщений как лотов."""
        soup = BeautifulSoup(html, "html.parser")
        out: list[scraper.Lot] = []
        for msg in soup.select("div.tgme_widget_message")[:max_msgs]:
            text_el = msg.select_one("div.tgme_widget_message_text")
            if not text_el:
                continue
            text = text_el.get_text(" ", strip=True)
            if not text or scraper.looks_like_buy_ad(text):
                continue
            link = msg.select_one("a.tgme_widget_message_date")
            tg_url = ("https://t.me/" + self.username + "/" + link["href"].rsplit("/", 1)[-1]
                      if link and link.get("href") else "")
            # если в посте есть внешняя ссылка на площадку (Авито/Мешок/Юла и т.п.)
            # — ведём на неё, а не на пост в Telegram (для агрегаторных каналов)
            url = self._source_link(msg, fallback=tg_url)
            out.append(scraper.lot_from_text(text, ref, source=f"tg:{self.username}", url=url))
        # оставляем только «содержательные»: есть цена или распознан тип детали
        return [l for l in out if l.price_rub > 0 or l.parts]

    @staticmethod
    def _source_link(msg, fallback: str) -> str:
        """Берёт из сообщения внешнюю ссылку на объявление (Авито/Мешок/Юла и т.п.).
        Если такой нет — возвращает fallback (ссылку на пост)."""
        for a in msg.select("a"):
            href = a.get("href", "") or ""
            hl = href.lower()
            if any(d in hl for d in ("avito.ru", "meshok.net", "youla.ru",
                                     "irr.ru", "auction.ru", "molotok.ru", "yula")):
                # проверяем, что это не просто «перейти на площадку», а ссылка на товар
                return href.replace("&amp;", "&")
        return fallback

    def scan(self, max_msgs: int, ref: Reference) -> list[scraper.Lot]:
        html = self.fetch_page()
        return self.parse_messages(html, max_msgs, ref)


_TG_DEFAULT = 40   # сообщений с одной ленты канала t.me/s по умолчанию


def scan_channels(channels: dict[str, str], max_msgs: int | None = None,
                  ref: Reference | None = None) -> list[scraper.Lot]:
    """Прогоняет все каналы из channels и собирает лоты."""
    from reference import Reference as _R
    ref = ref or _R.load()
    max_msgs = max_msgs or _TG_DEFAULT
    all_lots: list[scraper.Lot] = []
    for name, username in channels.items():
        if not username or username.startswith("название"):
            continue  # плейсхолдер
        try:
            lots = TelegramAdapter(username).scan(max_msgs, ref)
            all_lots.extend(lots)
        except Exception as exc:
            print(f"  [tg:{name} {username}] пропуск: {exc}")
    return all_lots


# ---------------------------------------------------------------------------
# VK (через официальный API, требуется бесплатный токен)
# ---------------------------------------------------------------------------

def vk_token() -> str:
    """Берёт токен из окружения VK_TOKEN или файла data/vk_token.txt."""
    tok = os.environ.get("VK_TOKEN", "").strip()
    if tok:
        return tok
    p = config.DATA_DIR / "vk_token.txt"
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
    return tok


class VkAdapter:
    """Читает стену публичной VK-группы через API wall.get."""

    name = "vk"

    def __init__(self, group: str, session: requests.Session | None = None,
                 token: str = ""):
        self.group = group
        self.token = token
        self.session = session or requests.Session()
        self.session.headers.update(config.HTTP_HEADERS)

    def _call(self, method: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v not in (None, "")}
        params.update(access_token=self.token, v=config.VK_API_VERSION)
        r = self.session.post(f"{config.VK_API}/{method}", data=params,
                              timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            raise RuntimeError("VK API: %s (%s)" % (body["error"].get("error_msg"),
                                                    body["error"].get("error_code")))
        return body

    def owner_id(self) -> int:
        # screen_name разрешаем в числовой id группы
        if self.group.lstrip("club").isdigit():
            return -int(self.group.lstrip("club"))
        body = self._call("groups.getById", {"group_ids": self.group, "fields": ""})
        g = body["response"][0]
        return -int(g["id"])

    def fetch_wall(self, count: int, ref: Reference) -> list[scraper.Lot]:
        owner = self.owner_id()
        body = self._call("wall.get",
                          {"owner_id": owner, "count": count, "filter": "all"})
        items = body.get("response", {}).get("items", [])
        return self.parse_wall(items, ref, owner)

    @staticmethod
    def parse_wall(items: list[dict], ref: Reference, owner: int) -> list[scraper.Lot]:
        """Превращает массив постов API VK в лоты (можно тестировать офлайн)."""
        out: list[scraper.Lot] = []
        for it in items:
            text = (it.get("text") or "").strip()
            if not text or scraper.looks_like_buy_ad(text):
                continue
            post_id = it.get("id")
            url = f"https://vk.com/wall{owner}_{post_id}" if post_id else ""
            out.append(scraper.lot_from_text(text, ref, source=f"vk:{owner}", url=url))
        # оставляем только «содержательные»: есть цена или распознан тип детали
        return [l for l in out if l.price_rub > 0 or l.parts]


def scan_vk_groups(groups: dict[str, str], max_posts: int | None = None,
                   ref: Reference | None = None, token: str = "",
                   pages: int | None = None) -> list[scraper.Lot]:
    """Прогоняет VK-группы. Без токена рендерит стены локальным браузером."""
    from reference import Reference as _R
    ref = ref or _R.load()
    max_posts = max_posts or config.VK_WALL_COUNT
    if not token:
        return _scan_vk_tokenless(groups, ref, pages)
    all_lots: list[scraper.Lot] = []
    for name, group in groups.items():
        try:
            lots = VkAdapter(group, token=token).fetch_wall(max_posts, ref)
            all_lots.extend(lots)
        except Exception as exc:
            print(f"  [vk:{name} {group}] пропуск: {exc}")
    return all_lots


def _scan_vk_tokenless(groups: dict[str, str], ref: Reference,
                       pages: int | None = None) -> list[scraper.Lot]:
    import vkbrowser
    browser = vkbrowser.find_browser()
    if not browser:
        print("  [vk] нет токена и не найден Chrome/Edge — VK пропущен.")
        return []
    pages = pages or config.VK_BROWSER_PAGES
    print(f"  [vk] токен не задан — отображаю стены локальным {browser.split(chr(92))[-1] or browser} "
          f"({pages} стр. стены)...")
    all_lots: list[scraper.Lot] = []
    for name, group in groups.items():
        try:
            lots = vkbrowser.scan_vk_tokenless(group, ref, browser, pages=pages)
            print(f"  [vk:{name}] постов с распознанными деталями: {len(lots)}")
            all_lots.extend(lots)
        except Exception as exc:
            print(f"  [vk:{name} {group}] пропуск: {exc}")
    return all_lots


def vk_search_posts(query: str, count: int, ref: Reference, token: str) -> list[scraper.Lot]:
    """newsfeed.search — ищет публичные записи VK по всему соцсети."""
    if not token:
        return []
    a = VkAdapter("", token=token)
    body = a._call("newsfeed.search",
                   {"q": query, "count": count, "extended": 0})
    items = body.get("response", {}).get("items", [])
    return VkAdapter.parse_wall(items, ref, owner=0)


def vk_search_market(query: str, count: int, ref: Reference, token: str) -> list[scraper.Lot]:
    """market.search — товарные объявления VK с ценами (лучше всего для «3x»)."""
    if not token:
        return []
    a = VkAdapter("", token=token)
    body = a._call("market.search", {"q": query, "count": count, "status": 0})
    items = body.get("response", {}).get("items", [])
    out: list[scraper.Lot] = []
    for it in items:
        text = it.get("title") or ""
        price = it.get("price", {}).get("amount", 0) or 0
        # сумма в «копейках» (в сотых рубля)
        price_rub = price / 100.0
        url = f"https://vk.com/market{it.get('owner_id','')}_{it.get('id','')}"
        lot = scraper.lot_from_text(text, ref, source="vk:market", url=url)
        lot.price_rub = price_rub if price_rub else lot.price_rub
        out.append(lot)
    return [l for l in out if l.price_rub > 0 or l.parts]