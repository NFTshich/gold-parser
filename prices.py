# -*- coding: utf-8 -*-
"""Цены драгметаллов за грамм (руб/грамм).

Источники по приоритету:
  1. РУЧНАЯ ЦЕНА  — data/manual_prices.json, если ты его заполнил
                     (пример: {"asof":"2026-09-28","prices":{"au":7200.0,...}})
  2. ОФИЦИАЛЬНЫЙ ЦБ — https://www.cbr.ru/scripts/xml_metall.asp?date_req=ДД/ММ/ГГГГ
                     (коды: 1 — золото, 2 — серебро, 3 — платина, 4 — палладий)
  3. ЗЕРКАЛО ЦБ    — https://www.cbr-xml-daily.ru/xml_metall.asp (запасной,
                     когда официальный закрыт «стеной согласия»)
  4. КЭШ           — data/metal_prices.json (последние успешные цены)

ЦБ публикует учётные цены за грамм по рабочим дням; бот ищет актуальную дату
за последние 7 дней и сохраняет кэш на день.
"""

from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import config

_ROW_NAMES = {"золото": "au", "серебро": "ag", "платина": "pt", "палладий": "pd"}

_OFFICIAL = "https://www.cbr.ru/scripts/xml_metall.asp?date_req={dmy}"
_MIRROR = "https://www.cbr-xml-daily.ru/xml_metall.asp?date_req={dmy}"


class CbrError(RuntimeError):
    """Не удалось получить цены ни от одного источника."""


class Metals:
    """Цены за грамм (руб/г), дата актуальности и источник."""

    def __init__(self, prices: dict[str, float], asof: str, source: str = ""):
        self.prices = {k: v for k, v in prices.items() if v}
        self.asof = asof
        self.source = source

    def per_gram(self, metal: str) -> float:
        return self.prices.get(metal, 0.0)

    def grams_of(self, metal: str, rub: float) -> float:
        pg = self.per_gram(metal)
        return rub / pg if pg else 0.0

    def summary(self) -> str:
        names = {"au": "Золото", "pd": "Палладий", "pt": "Платина"}
        parts = [f"{names[m]} {self.prices[m]:,.2f} руб/г"
                 for m in ("au", "pd", "pt") if m in self.prices]
        return " · ".join(parts)


# ---------------------------------------------------------------------------
# Скачивание / парсинг
# ---------------------------------------------------------------------------

def _fetch_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url, headers={"User-Agent": config.HTTP_HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT) as resp:
        data = resp.read()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        return data, ctype


def _decode(data: bytes, ctype: str = "") -> str:
    enc = None
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        enc = m.group(1)
    if not enc:
        m = re.search(rb"encoding=[\"']([\w-]+)[\"']", data[:200])
        if m:
            enc = m.group(1).decode("ascii", "replace")
    for cand in (enc or "", "utf-8", "windows-1251"):
        if not cand:
            continue
        try:
            return data.decode(cand)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:40].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _parse_metals_xml(text: str) -> dict[str, float]:
    text = re.sub(r"<\?xml[^>]*\?>", "", text)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise CbrError(f"непарсибельный XML: {exc}") from exc
    inv = {v: k for k, v in config.CBR_METAL_CODES.items()}
    out: dict[str, float] = {}
    for metal in root.iter("Metal"):
        code = metal.get("Code") or ""
        col = (metal.findtext("Col") or "").strip().lower()
        val = metal.findtext("Sell") or metal.findtext("Buy") or "0"
        key = _ROW_NAMES.get(col) or inv.get(code)
        if key:
            out[key] = _to_float(val)
    if not out:
        raise CbrError("в ответе нет ни одного металла")
    return out


def _to_float(s: str) -> float:
    s = s.strip().replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _try_providers(d: date) -> dict[str, float] | None:
    dmy = d.strftime("%d/%m/%Y")
    for name, tpl in (("официальный ЦБ", _OFFICIAL), ("зеркало cbr-xml-daily", _MIRROR)):
        try:
            url = tpl.format(dmy=dmy)
            data, ctype = _fetch_bytes(url)
            text = _decode(data, ctype)
            if _looks_like_html(text):
                raise CbrError(f"{name}: отдал HTML (стена согласия)")
            prices = _parse_metals_xml(text)
            if prices:
                return prices
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Ручная цена / кэш
# ---------------------------------------------------------------------------

def _load_manual() -> tuple[dict[str, float], str] | None:
    p = config.MANUAL_PRICES
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        prices = dict(data.get("prices") or {})
        if "au" in prices:
            return prices, str(data.get("asof") or date.today().isoformat())
    except Exception:
        return None
    return None


def _load_cache() -> tuple[dict[str, float], str] | None:
    try:
        data = json.loads(config.CACHE_PRICES.read_text(encoding="utf-8"))
        return dict(data.get("prices") or {}), str(data.get("asof") or "")
    except Exception:
        return None


def _save_cache(prices: dict[str, float], asof: str) -> None:
    try:
        config.ensure_dirs()
        payload = {
            "_comment": "Кэш цен ЦБ. Источник по приоритету в prices.py.",
            "asof": asof,
            "prices": prices,
        }
        config.CACHE_PRICES.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def seed_cache_demo() -> None:
    """Демо-кэш для первого запуска в изолированной среде (без интернета).
    Реальные цены ЦБ при первом живом запуске перезапишут кэш."""
    demo = {
        "asof": date.today().isoformat(),
        "prices": {"au": 7200.0, "pd": 3100.0, "pt": 2900.0, "ag": 95.0},
    }
    try:
        config.ensure_dirs()
        config.CACHE_PRICES.write_text(
            json.dumps({"_comment": "ДЕМО-цены (нет живого фида ЦБ в этой сети). "
                                     "При живом запуске кэш перезапишется реальными.",
                        **demo}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_metals(allow_cache: bool = True) -> Metals:
    """Актуальные цены за грамм с учётом всех источников по приоритету.

    Сеть ходим только если кэша НЕТ (или allow_cache=False). Иначе возвращаем
    кэш сразу — свежесть цены за день не критична, а сетевые пробы к ЦБ
    могут висеть (особенно через некоторые прокси/VPN).
    """
    today = date.today()

    manual = _load_manual()
    if manual:
        prices, asof = manual
        return Metals(prices, asof, source="ручная цена (manual_prices.json)")

    if allow_cache:
        cached = _load_cache()
        if cached and "au" in cached[0]:
            return Metals(cached[0], cached[1] or "?", source=f"кэш {cached[1] or ''}".strip())

    # сетевые пробы — только если кэша нет
    for back in range(0, 8):
        d = today - timedelta(days=back)
        prices = _try_providers(d)
        if prices:
            _save_cache(prices, d.isoformat())
            return Metals(prices, d.isoformat(), source="ЦБ РФ")

    raise CbrError(
        "Ни один источник цен ЦБ недоступен, ручная цена и кэш отсутствуют. "
        f"Заполни {config.MANUAL_PRICES.name} (шаблон: manual_prices.example.json) "
        "или запусти в сети, откуда открывается cbr.ru.")