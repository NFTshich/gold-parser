# -*- coding: utf-8 -*-
"""Расчёт стоимости металла в лоте и маржи.

Логика «металл в 3× больше цены лота»:
    metal_value = au_g*Цаu + pd_g*Цpd + pt_g*Цpt
    ratio = metal_value / ask_price
    net   = metal_value - ask_price
Лот считается выгодным, если ratio >= MIN_RATIO и net >= MIN_NET_PROFIT_RUB.

Внимание: серебро по ТЗ НЕ учитываем в марже. При желании добавь 'ag' в
config.INTERESTED_METALS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import config
from prices import Metals
from reference import Part


@dataclass
class Lot:
    """Одно объявление/лот из поиска или вручную."""

    title: str
    price_rub: float
    url: str = ""
    source: str = ""
    parts: list[Part] = field(default_factory=list)

    def __post_init__(self):
        # Количество «шт/штук» из заголовка, если указано (иначе 1).
        self.qty: int = parse_qty(self.title)

    def metal_value(self, metals: Metals) -> float:
        tot = 0.0
        for p in self.parts:
            mg = p.mg_by_metal()
            tot += (mg["au"] / 1000.0) * metals.per_gram("au")
            tot += (mg["pd"] / 1000.0) * metals.per_gram("pd")
            tot += (mg["pt"] / 1000.0) * metals.per_gram("pt")
        return tot * self.qty

    def total_mg(self) -> dict[str, float]:
        mg = {"au": 0.0, "pd": 0.0, "pt": 0.0}
        for p in self.parts:
            for m in mg:
                mg[m] += p.mg_by_metal()[m]
        return {k: v * self.qty for k, v in mg.items()}


_QTY_RE = re.compile(r"(?<!\d)(\d{1,4})\s*(?:шт|штук|штуки|шта|щт|pcs)", re.IGNORECASE)


def parse_qty(text: str) -> int:
    m = _QTY_RE.search(text or "")
    return int(m.group(1)) if m else 1


@dataclass
class Valuation:
    lot: Lot
    metal_value: float
    net: float
    ratio: float
    mg: dict[str, float]

    @property
    def is_profitable(self) -> bool:
        """Выгодно: металл в 3+ раза дороже цены лота И металл стоит не меньше
        MIN_METAL_VALUE_RUB (чтобы не связываться с копеечной мелочью)."""
        if self.lot.price_rub <= 0:
            return False
        return (self.ratio >= config.MIN_RATIO
                and self.metal_value >= config.MIN_METAL_VALUE_RUB)

    @property
    def good_ratio(self) -> bool:
        """Металл в 3+ раза дороже цены (без учёта абсолютных сумм)."""
        return self.lot.price_rub > 0 and self.ratio >= config.MIN_RATIO


def valuate(lot: Lot, metals: Metals) -> Valuation:
    mv = lot.metal_value(metals)
    price = lot.price_rub
    net = mv - price
    ratio = (mv / price) if price > 0 else 0.0
    return Valuation(lot=lot, metal_value=mv, net=net, ratio=ratio, mg=lot.total_mg())


def format_mg(mg: dict[str, float]) -> str:
    parts = []
    for m in ("au", "pd", "pt"):
        v = mg.get(m, 0.0)
        if v > 0:
            parts.append(f"{m.upper()} {v:,.1f} мг")
    return ", ".join(parts) if parts else "—"