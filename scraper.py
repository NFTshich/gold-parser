# -*- coding: utf-8 -*-
"""Поиск объявлений.

Реальность: Авито, Юла, Мешок и большинство барахолок жёстко режут
простой requests-скрапинг (антибот, JS, редиректы), что подтверждено тестами.
Поэтому основной надёжный путь — ручной/пакетный ввод лотов (см. parse_blob
и parse_csv): ты и так видишь цену на сайте, а бот считает металл.

Для тех, кто захочет скрапить дальше, оставлен каркас адаптеров ScraperAdapter.
Заполни селекторы в подклассах под конкретный сайт и раскомментируй в
SITE_ADAPTERS — фреймворк возьмёт их автоматически.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass

import config
from calculator import Lot
from reference import Reference


# ---------------------------------------------------------------------------
# Ручной / пакетный ввод
# ---------------------------------------------------------------------------

def parse_blob(text: str, ref: Reference) -> list[Lot]:
    """Парсит многострочный текст вида:
        <заголовок> — <цена> руб
        https://...  <заголовок> <цена>
    Для каждой повторяющейся позиции подбирает детали из справочника.
    Возвращает лоты с пустой ценой, если цену не нашли (цена 0).
    """
    lots: list[Lot] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        lots.append(lot_from_text(line, ref, source="ввод"))
    return lots


def lot_from_text(text: str, ref: Reference, source: str = "", url: str = "") -> Lot:
    """Собирает Lot из свободного текста: цена + лучшее совпадение по справочнику."""
    price, cleaned = _extract_price(text or "")
    title = cleaned.strip() or (text or "").strip()
    lot = Lot(title=title, price_rub=price, url=url or _extract_url(text or ""),
              source=source, parts=_best_parts(ref, title))
    # Явно «не наша» тематика (одежда/обувь/аксессуары/недвижимость и т.п.)
    # всегда отсекается, даже если случайно сматчилось слово справочника
    # (например «оплата» -> «плата», «кроссовки» -> «разъём» из описания).
    if _looks_unrelated(title):
        lot.parts = []
        lot.price_rub = 0.0
    return lot


# Слова, которые однозначно означают «не про радиодетали/драгметаллы».
_UNRELATED_WORDS = (
    # одежда и обувь
    "кроссовк", "кед", "ботинк", "обув", "сапог", "туфл", "джинс", "брюк", "штаны",
    "плать", "юбк", "кофт", "свитер", "футболк", "рубашк", "куртк", "пальто",
    "шуб", "блузк", "толстовк", "худи", "сорочк", "бюстгальтер", "лифчик", "трус",
    "колготк", "носк", "шарф", "шапк", "кепк", "перчат",
    # аксессуары / мелочи не по теме
    "сумк", "рюкзак", "кошел", "ремень", "бижутер", "серьг", "кулон", "колье",
    "ожерель", "часы наручные", "браслет", "очк", "зонт",
    # мебель / быт / прочее явно не электроника
    "диван", "кресл", "кроват", "шкаф", "стол обеден", "стул", "кухн", "холодильник",
    "стирал", "пылесос", "утюг", "микроволнов",
    # недвижимость / транспорт общего назначения
    "квартир", "дом прод", "дача", "комната", "участок", "гараж",
    "машина", "автомобил", "легков", "велосипед",
    # банковское/бытовое, где слово «плата» не значит «печатная плата»
    "оплата", "оплачен", "проплат",
    # услуги / работы (не лот-деталь)
    "монтаж", "гирлянд", "украшение", "покраш", "установк", "ремонт телеф",
    "пайка микросхем", "реболлинг", "рентген-контроль", "установка",
    "починю", "отремонтир", "услуг", "помогу", "аренда", "прокат",
)
# НО: некоторые слова могут входить в названия электроники в редких случаях,
# поэтому срабатываем только если фраза явно про это (суффикса достаточно).


def _looks_unrelated(title: str) -> bool:
    t = (title or "").lower()
    return any(w in t for w in _UNRELATED_WORDS)


def _best_parts(ref: Reference, title: str) -> list:
    """Одно лучшее совпадение типа детали (консервативная оценка)."""
    best = ref.best_match(title)
    return [best] if best else []


_PRICE_RE = re.compile(r"(\d[\d\s\u00a0.,]*)\s*(?:руб\.?|р\.?|₽|\$)", re.IGNORECASE)
# «Цена: 44.000», «цена 44 000», «за 2000 р» — число, помеченное словом «цен»
_LABELED_RE = re.compile(r"(?:цена|ценою|стоит|за)\s*[:–—-]?\s*([\d][\d\s\u00a0.,]*)(?:\s*(?:руб\.?|р\.?|₽|\$))?", re.IGNORECASE)


def _to_num(txt: str) -> float | None:
    """'44.000'/'44 000'/'44000'/'44,000' -> 44000.0; None если не число."""
    t = txt.replace("\u00a0", " ").strip()
    t = t.replace(" ", "").replace(",", "")
    if "." in t:
        int_part, _, frac = t.partition(".")
        if frac.isdigit() and int_part.isdigit():
            return float(int_part) * 1000 if len(frac) == 3 else float(t)
    if t.isdigit():
        return float(t)
    return None


def _extract_price(s: str) -> tuple[float, str]:
    # 1) число + валюта
    m = _PRICE_RE.search(s)
    if m:
        v = _to_num(m.group(1))
        if v is not None:
            return v, s[:m.start()] + s[m.end():]

    # 2) «Цена/за: N» — число, помеченное словом «цена»
    m = _LABELED_RE.search(s)
    if m:
        v = _to_num(m.group(1))
        if v is not None and 1 <= v <= 50_000_000:
            return v, s[:m.start()] + s[m.end():]

    # 3) последнее разумное число строки как цена (без слова «руб»)
    tokens = re.split(r"\s+", s.strip())
    for tok in reversed(tokens):
        t = tok.strip(" .,;:")
        if t.isdigit() and 2 <= len(t) <= 7:
            v = int(t)
            if 1 <= v <= 50_000_000:   # разумный ценник; телефоны — мимо
                return float(v), s.replace(tok, " ", 1).strip()
    return 0.0, s


_PHONE_RE = re.compile(r"(?:\+?7|8)[\s\-(\u00a0]?\d{3}[\s\-)\u00a0]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
_BUY_WORDS = ("скупк", "скупаем", "покупк", "покупаем", "купим", "куплю", "принимаем",
              "нужны", "требу", "выкупим", "выкуп", "закупаю", "закупка", "на постоянно",
              "обмен", "обменяю", "возьму", "возьмём", "нужно", "нужна", "нужен",
              "ищу", "ищем", "приму в дар", "даром заберу")
# Маркетинговые «справки» скупщиков: не лот продажи, а реклама-обзор «сколько
# драгметаллов в приборе» + ссылка на их сайт/контакты. Такое фолсит ratio и заспамливает.
_INFO_WORDS = (
    "не спешите выбрасывать", "не спеши выбрасывать", "не выкидывайте", "не выкидывай",
    "спешите выкидывать", "наш сайт", "наши контакты", "узнавать подробности",
    "узнать подробности", "содержание драгоценных металлов", "содержание драгметаллов",
    "содержание ценных металлов", "это ценное", "получить бесплатную оценку",
    "бесплатную консультацию", "оценим вашу", "высоким ценам", "по самым высоким ценам",
)


def looks_like_buy_ad(text: str) -> bool:
    """True, если текст похож на заявку/рекламу СКУПЩИКА, а не на лот продажи."""
    t = (text or "").lower()
    if not t:
        return False
    if any(w in t for w in _BUY_WORDS):
        return True
    # рекламная справка о содержании металлов: явные маркеры скупщика + контакт/сайт
    if any(w in t for w in _INFO_WORDS):
        return True
    return False


def _extract_url(s: str) -> str:
    m = re.search(r"https?://\S+", s)
    return m.group(0) if m else ""


def _strip_url(s: str, url: str) -> str:
    if not url:
        return s.strip()
    s = s.replace(url, " ").strip(" -–—")
    return s or url


def parse_csv(path, ref: Reference) -> list[Lot]:
    """Импорт CSV со столбцами: title;price;url (url необязателен)."""
    from pathlib import Path
    p = Path(path)
    lots: list[Lot] = []
    with p.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            title = (row.get("title") or "").strip()
            if not title:
                continue
            price = float((row.get("price") or "0").replace(",", ".").strip() or 0)
            url = (row.get("url") or "").strip()
            lots.append(Lot(title=title, price_rub=price, url=url,
                            source=f"csv:{p.name}",
                            parts=_best_parts(ref, title)))
    return lots


# ---------------------------------------------------------------------------
# Каркас для скрапинга (на будущее)
# ---------------------------------------------------------------------------

@dataclass
class RawAd:
    title: str
    price_rub: float
    url: str = ""


class ScraperAdapter:
    """Базовый адаптер площадки. Переопределяй __init__/search."""

    name = "base"
    search_url_template = ""   # пример: "https://site.example/search?q={query}"

    def __init__(self, session):
        self.session = session

    def search(self, query: str, max_ads: int) -> list[RawAd]:
        raise NotImplementedError


SITE_ADAPTERS: list[type[ScraperAdapter]] = []
# Пример включения адаптера после его реализации:
#   from scrapers.avito_adapter import AvitoAdapter
#   SITE_ADAPTERS.append(AvitoAdapter)


def search_sites(query: str, ref: Reference, max_ads: int | None = None) -> list[Lot]:
    """Прогоняет запрос по включённым адаптерам. Пока адаптеров нет —
    возвращает пусто и подсказывает ручной режим."""
    if not SITE_ADAPTERS:
        return []
    max_ads = max_ads or config.MAX_ADS_PER_SITE
    import requests
    session = requests.Session()
    session.headers.update(config.HTTP_HEADERS)
    out: list[Lot] = []
    for adapter_cls in SITE_ADAPTERS:
        try:
            adapter = adapter_cls(session)
            for ad in adapter.search(query, max_ads):
                out.append(Lot(title=ad.title, price_rub=ad.price_rub, url=ad.url,
                               source=adapter.name, parts=_best_parts(ref, ad.title)))
        except Exception as exc:
            print(f"  [скрапинг {adapter_cls.name}] пропуск: {exc}")
    return out