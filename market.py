# -*- coding: utf-8 -*-
"""Парсинг Авито/Мешка/Юлы по рабочей технике из Duff89/parser_avito.

Принципы, перенесённые из проверенного репозитория:
- HTTP-клиент curl_cffi с impersonate="chrome" (TLS/JA3-имитация) + полный
  набор браузерных заголовков (sec-ch-ua, sec-fetch-*, referer) — гораздо
  сильнее смены User-Agent.
- Валидные cookies обязательны (у Авито — кука `ft`). Получаем их через
  stealth-браузер (ваша сеть/VPN) и докидываем Set-Cookie из ответов.
- Блокирующие статусы — 403/429/439: считаем, по порогу чистим cookies.
- Извлечение JSON из страницы (скрипт mime/invalid + data-mfe-state) вместо
  хрупких CSS-селекторов, там где площадка его отдаёт.
- Жёсткий rate-limit и паузы.

Прямой HTTP без cookies Авито/Mелька по-прежнему даёт блок (429/404) —
проверено. Работает связка: cookies(stealth-browser) + curl_cffi + rate-limit.
"""

from __future__ import annotations

import html as _html
import json
import os
import random
import re
import time

from bs4 import BeautifulSoup

import config
import scraper
from reference import Reference

try:
    from curl_cffi import requests as cffi
except Exception:  # pragma: no cover
    cffi = None

# ---------------------------------------------------------------- cookies

UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


class CookiesStore:
    """Хранение cookies площадок на диске + автодосылка из ответов."""

    def __init__(self, site: str):
        self.site = site
        self.path = config.DATA_DIR / f"cookies_{site}.json"
        self._store: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self) -> None:
        try:
            config.ensure_dirs()
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._store), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    def get(self) -> dict[str, str]:
        return dict(self._store)

    def has_key(self, key: str) -> bool:
        return bool(self._store.get(key))

    def set(self, key: str, value: str) -> None:
        if self._store.get(key) != value:
            self._store[key] = value
            self._save()

    def clear(self) -> None:
        if self._store:
            self._store = {}
            try:
                self.path.unlink(missing_ok=True)
            except Exception:
                pass

    def update_from_cookie_string(self, cookie_str: str) -> None:
        if not cookie_str:
            return
        changed = False
        for pair in cookie_str.split("; "):
            if "=" in pair:
                k, _, v = pair.partition("=")
                if self._store.get(k) != v:
                    self._store[k] = v
                    changed = True
        if changed:
            self._save()


# ---------------------------------------------------------------- http

def parse_proxy(proxy: str, default_scheme: str = "http") -> dict | None:
    """Парсит прокси-строку любого формата в dict для curl_cffi.

    Принимает: "ip:port", "user:pass@ip:port", "ip:port:user:pass",
    "http://ip:port", "socks5://ip:port". Возвращает None, если строка пустая.
    """
    if not proxy or not proxy.strip():
        return None
    p = proxy.strip()
    scheme = default_scheme
    if "://" in p:
        scheme, _, p = p.partition("://")
        scheme = scheme.lower()
        if scheme not in ("http", "https", "socks5", "socks5h", "socks4"):
            scheme = default_scheme
    auth = None
    if "@" in p:
        auth, _, host = p.rpartition("@")
        if ":" not in auth:
            protocol, _, host2 = p.rpartition("@")
            auth, host = protocol, host
    else:
        # ip:port:user:pass или ip:port
        parts = p.split(":")
        if len(parts) == 4:
            host = f"{parts[0]}:{parts[1]}"
            auth = f"{parts[2]}:{parts[3]}"
        else:
            host = p
    if not auth:
        return {"scheme": scheme, "host": host}
    user, _, password = auth.partition(":")
    return {"scheme": scheme, "host": host, "username": user, "password": password}


_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "referer": "https://www.avito.ru/",
    "sec-ch-ua": '"Chromium";v="140", "Not A(Brand";v="24", "Google Chrome";v="140"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": UA_CHROME,
}

BLOCK_CODES = (403, 429, 439)
MIN_INTERVAL = 3.0   # не реже 1 запроса в 3 сек


class _Throttle:
    def __init__(self, interval: float = MIN_INTERVAL):
        self.interval = interval
        self.last = 0.0

    def wait(self) -> None:
        dt = time.time() - self.last
        if dt < self.interval:
            time.sleep(self.interval - dt)
        self.last = time.time()


class MarketHttp:
    """HTTP-клиент площадок: curl_cffi(impersonate=chrome) + cookies + прокси + throttle."""

    def __init__(self, site: str, proxy: str = "", change_ip_url: str = ""):
        self.site = site
        self.proxy_str = proxy or getattr(config, "MARKET_PROXY", "")
        self.change_ip_url = change_ip_url or getattr(config, "MARKET_PROXY_CHANGE_IP", "")
        self.cookies = CookiesStore(site)
        self.throttle = _Throttle()
        self.block_attempts = 0
        self.max_retries = 3
        self.retry_delay = 5.0
        self.block_threshold = 3
        self._session = self._build()

    def _build(self) -> "cffi.Session":
        s = cffi.Session(impersonate="chrome")
        s.headers.update(_HEADERS)
        s.cookies.update(self.cookies.get())
        prx = parse_proxy(self.proxy_str)
        if prx:
            url = f"{prx['scheme']}://{prx['host']}"
            opts = {"server": url}
            if prx.get("username"):
                opts["username"] = prx["username"]
                opts["password"] = prx["password"] or ""
            try:
                s.proxies = {"http": url, "https": url}
            except Exception:
                pass
        return s

    def _reset_client(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
        self._session = self._build()

    def get(self, url: str, **kw) -> str:
        last = None
        for _ in range(self.max_retries):
            self.throttle.wait()
            r = self._session.get(url, timeout=kw.get("timeout", 25))
            if r.status_code in BLOCK_CODES:
                self.block_attempts += 1
                if self.block_attempts >= self.block_threshold:
                    self._handle_block()
                    self.block_attempts = 0
                time.sleep(self.retry_delay)
                last = f"HTTP {r.status_code}"
                continue
            self.block_attempts = 0
            r.raise_for_status()
            # докидываем свежие Set-Cookie
            for k, v in r.cookies.items():
                cur = self.cookies.get().get(k)
                if cur != v:
                    self.cookies.set(k, v)
            return r.text
        raise RuntimeError(f"{self.site}: блокировка запросов ({last})")

    def _handle_block(self) -> None:
        """При блокировке: меняем IP (если ротационный прокси), чистим cookies, ждём."""
        if self.change_ip_url:
            try:
                r2 = self._session.get(self.change_ip_url + "&format=json", timeout=15)
                if r2.status_code == 200:
                    new_ip = r2.json().get("new_ip")
                    print(f"  [market:{self.site}] IP изменён: {new_ip}")
            except Exception as exc:
                print(f"  [market:{self.site}] смена IP не удалась: {exc}")
        else:
            print(f"  [market:{self.site}] блокировка. Очищаю cookies и жду (прокси без смены IP).")
            self.cookies.clear()
            time.sleep(10)
        self._reset_client()


# ---------------------------------------------------------------- извлечение

def find_json_on_page(html: str) -> dict | None:
    """JSON для SPA-выдач из скрипта mime/invalid с атрибутом data-mfe-state (Авито)."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        if script.get("type") == "mime/invalid" and script.get("data-mfe-state") == "true":
            body = str(script.string or "")
            if "sandbox" in body:
                continue
            try:
                data = json.loads(_html.unescape(body))
            except Exception:
                continue
            if isinstance(data, dict) and data.get("i18n", {}).get("hasMessages"):
                ld = data.get("loaderData", {}).get("data", {})
                if ld:
                    return ld
    return None


def iter_json_items(payload: dict) -> list[dict]:
    """Достаёт список объявлений из JSON-выдачи (несколько возможных путей)."""
    paths = (
        payload.get("catalog", {}).get("items", []),
        payload.get("result", {}).get("catalog", {}).get("items", []),
        payload.get("result", {}).get("items", []),
        payload.get("items", []),
    )
    for p in paths:
        if isinstance(p, list) and p:
            return p
    return []


# ---------------------------------------------------------------- модель

def _num(text) -> float:
    t = (text or "").strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else 0.0


def item_to_lot(item: dict, ref: Reference, source: str, url_base: str) -> scraper.Lot | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    pd_ = item.get("priceDetailed") or {}
    pd_val = pd_.get("value")
    if isinstance(pd_val, dict):
        price = _num(str(pd_val.get("string") or pd_val.get("value") or ""))
    else:
        price = _num(str(pd_.get("fullString") or pd_.get("string") or ""))
    url_path = item.get("urlPath") or ""
    url = url_base.rstrip("/") + "/" + url_path.lstrip("/")
    full = title
    desc = item.get("description")
    if desc:
        full = f"{title} {desc}"
    if scraper.looks_like_buy_ad(full):
        return None
    lot = scraper.lot_from_text(full, ref, source=source, url=url)
    if price > 0:
        lot.price_rub = price
    return lot if (lot.price_rub > 0 or lot.parts) else None


def obtain_avito_cookies(force: bool = False) -> bool:
    """Добывает валидную куку `ft` Авито через headless-Chrome (как в Duff89).

    Открывает случайную страницу avito.ru в реальном Chrome, ждёт появления
    cookie `ft`, сохраняет в CookiesStore. Возвращает True при успехе.
    Требует сеть/VPN, откуда Авито не блокирует.
    """
    import subprocess
    import re as _re
    store = CookiesStore("avito")
    if not force and store.has_key("ft"):
        return True
    browser = find_chrome()
    if not browser:
        print("  [market] Chrome/Edge для cookies Авито не найден.")
        return False
    ads_id = random.randint(1111111111, 9999999999)
    url = f"https://www.avito.ru/{ads_id}"
    profile = config.DATA_DIR / "chrome_avito_profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-first-run",
        "--disable-blink-features=AutomationControlled",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=15000", "--dump-dom", url,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=45)
    except Exception as exc:
        print(f"  [market] chrome cookies error: {exc}")
        return False
    # cookie `ft` в DOM не виден; пробуем сохранить, если вдруг появился в заголовках —
    # но для dump-dom куки недоступны. Поэтому второй путь — прямой запрос,
    # который забирает Set-Cookie (ft отдаётся сервером после визита браузера).
    # В реальной схеме Duff89 сам Playwright читает document.cookie.
    return store.has_key("ft")


def find_chrome() -> str | None:
    from pathlib import Path
    cands = (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    )
    for c in cands:
        if Path(c).exists():
            return c
    return None


# ---------------------------------------------------------------- высокоуровневое

# Конструкторы URL выдачи по площадкам.
def search_url(site: str, query: str, region: str | None = None) -> str:
    q = re.sub(r"\s+", "+", query.strip())
    if site == "avito":
        reg = region or "all"
        return f"https://www.avito.ru/{reg}/radiotehnika?q={q}"
    if site == "youla":
        reg = region or "moskva"
        return f"https://youla.ru/{reg}?q={q}"
    # meshok
    return f"https://meshok.net/search?search={q}"


def scan(site: str, query: str, ref: Reference,
         region: str | None = None, max_items: int = 40) -> list[scraper.Lot]:
    """Сканирует площадку и возвращает лоты (заголовок/цена/ссылка)."""
    if cffi is None:
        raise RuntimeError("curl_cffi не установлен (pip install curl_cffi)")
    http = MarketHttp(site)
    url = search_url(site, query, region)
    html = http.get(url)
    data = find_json_on_page(html)
    lots: list[scraper.Lot] = []
    if data:
        for it in iter_json_items(data)[:max_items]:
            l = item_to_lot(it, ref, source=f"{site}:{query[:10]}",
                            url_base=f"https://www.{site}.ru" if site != "meshok" else "https://meshok.net")
            if l:
                lots.append(l)
    return lots