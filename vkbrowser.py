# -*- coding: utf-8 -*-
"""VK БЕЗ токена: рендерим публичную стену локальным браузером.

Официальный API VK требует access_token (проверено: wall.get/market.get
возвращают «token required»), а посты на сайте грузятся JS — простым requests
их не достать. Решение: запускаем установленный Chrome/Edge в headless-режиме,
страница исполняет JS и отдаёт готовый DOM, который парсим BeautifulSoup.
Это tokenless и без дополнительных pip-пакетов (нужен лишь local Chrome/Edge).

Выхода два этапа на группу:
  1. рендер https://vk.com/<группа>  -> ищем owner_id из id поста "wpt-<owner>_<post>";
  2. рендер https://vk.com/wall-<owner> -> парсим последние посты стены.
"""

from __future__ import annotations

import re
import shutil  # noqa: F401 (для возможного поиска по PATH)
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup

import config
import scraper
from reference import Reference

_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


def find_browser() -> str | None:
    for cand in _CHROME_CANDIDATES:
        if Path(cand).exists():
            return cand
    for name in ("chrome", "chromium", "msedge", "google-chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def render_dom(url: str, browser: str | None = None, timeout: int = 45) -> str:
    """Возвращает DOM HTML страницы, отрендеренный headless-браузером."""
    browser = browser or find_browser()
    if not browser:
        raise RuntimeError("Chrome/Edge не найден — нужен для VK без токена.")
    profile = config.DATA_DIR / "chrome_vk_profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=15000",
        "--dump-dom",
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(f"chrome ошибка (код {proc.returncode}): {proc.stderr[:200]}")
    return proc.stdout or ""


_OWNER_RE = re.compile(r"wpt-(-?\d+)_(\d+)")


def discover_owner(html: str) -> int | None:
    m = _OWNER_RE.search(html)
    if m:
        return int(m.group(1))
    m = re.search(r'"owner_id":\s*(-?\d+)', html)
    return int(m.group(1)) if m else None


def parse_wall_posts(html: str, ref: Reference, source: str) -> list[scraper.Lot]:
    """Извлекает посты стены (div.wall_post_cont) из отрендеренного DOM."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[scraper.Lot] = []
    for post in soup.select("div.wall_post_cont"):
        pid = post.get("id") or ""
        text = post.get_text(" ", strip=True)
        if not text or scraper.looks_like_buy_ad(text):
            continue
        owner = post.get("data-post-id") or pid.replace("wpt-", "").replace("_", "_")
        url = ""
        m = _OWNER_RE.search(pid)
        if m:
            url = f"https://vk.com/wall{m.group(1)}_{m.group(2)}"
        lot = scraper.lot_from_text(text, ref, source=source, url=url)
        if lot.price_rub > 0 or lot.parts:
            out.append(lot)
    # дедупликация по url
    seen = set()
    uniq = []
    for l in out:
        if l.url and l.url in seen:
            continue
        if l.url:
            seen.add(l.url)
        uniq.append(l)
    return uniq


def scan_vk_tokenless(group: str, ref: Reference, browser: str | None = None,
                      pages: int = 1) -> list[scraper.Lot]:
    """Обход группы без токена: страница -> owner -> стена (с листанием) -> посты.

    `pages` — сколько блоков стены подгрузить (один блок ~20 постов),
    листаем веб-стену через ?offset= и дедуплицируем по ссылке.
    """
    page = render_dom(f"https://vk.com/{group}", browser)
    owner = discover_owner(page)
    if owner is None:
        # парсим то, что есть на странице группы (хотя бы пины)
        return parse_wall_posts(page, ref, source=f"vk:{group}")
    seen_urls: set[str] = set()
    out: list[scraper.Lot] = []
    # стена группы — по отрицательному owner id (vk.com/wall-<id>)
    for off in range(0, pages * 20, 20):
        wall = render_dom(f"https://vk.com/wall-{owner}?offset={off}", browser)
        for lot in parse_wall_posts(wall, ref, source=f"vk:{owner}"):
            if lot.url and lot.url in seen_urls:
                continue
            if lot.url:
                seen_urls.add(lot.url)
            out.append(lot)
    return out