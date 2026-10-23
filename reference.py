# -*- coding: utf-8 -*-
"""Справочник деталей и содержание драгметаллов.

Читает components.csv (разделитель ';', кодировка utf-8-sig для русских Excel):
  category;name;desc;au_mg;au_hi;pd_mg;pd_hi;pt_mg;pt_hi;note

Значения содержания — на ОДНУ штуку, миллиграммы.
au_mg..au_hi — диапазон; если hi<=lo верно, берём lo как точечное значение.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field

import config


@dataclass
class Part:
    category: str
    name: str
    desc: str
    au_mg: float
    au_hi: float
    pd_mg: float
    pd_hi: float
    pt_mg: float
    pt_hi: float
    note: str
    confidence: str = "estimate"   # exact / estimate / wide (насколько надёжно содержание)
    keywords: list[str] = field(init=False)

    def __post_init__(self):
        # Слова из названия (коды моделей весят сильнее) и из описания.
        # Название повторяем в списке несколько раз, чтобы x3 увеличивало вес.
        name_toks = _words(self.name, 2)
        desc_toks = _words(self.desc, 3)
        self.keywords = name_toks + name_toks + name_toks + desc_toks

    def au(self) -> float:
        return _mid(self.au_mg, self.au_hi)

    def pd(self) -> float:
        return _mid(self.pd_mg, self.pd_hi)

    def pt(self) -> float:
        return _mid(self.pt_mg, self.pt_hi)

    def has_metals(self) -> bool:
        return self.au() > 0 or self.pd() > 0 or self.pt() > 0

    def mg_by_metal(self) -> dict[str, float]:
        return {"au": self.au(), "pd": self.pd(), "pt": self.pt()}


def _words(s: str, min_len: int) -> list[str]:
    return [w for w in re.findall(r"[а-яёa-z0-9]+", (s or "").lower()) if len(w) >= min_len]


def _mid(lo: float, hi: float) -> float:
    lo = max(0.0, float(lo))
    hi = max(0.0, float(hi))
    return lo if hi <= lo else (lo + hi) / 2.0


class Reference:
    """База деталей с поиском по ключевым словам."""

    def __init__(self, parts: list[Part]):
        self.parts = parts

    @classmethod
    def load(cls) -> "Reference":
        path = config.COMPONENTS_CSV
        parts: list[Part] = []
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                try:
                    parts.append(Part(
                        category=(row.get("category") or ""),
                        name=(row.get("name") or ""),
                        desc=(row.get("desc") or ""),
                        au_mg=_f(row.get("au_mg")),
                        au_hi=_f(row.get("au_hi")),
                        pd_mg=_f(row.get("pd_mg")),
                        pd_hi=_f(row.get("pd_hi")),
                        pt_mg=_f(row.get("pt_mg")),
                        pt_hi=_f(row.get("pt_hi")),
                        note=(row.get("note") or ""),
                        confidence=(row.get("confidence") or "estimate").strip(),
                    ))
                except Exception:
                    continue  # пропускаем битые строки
        return cls(parts)

    def match_by_text(self, text: str) -> list[Part]:
        """Возвращает записи, чьи слова встречаются в тексте объявления."""
        t = (text or "").lower()
        hits = []
        for p in self.parts:
            if any(k in t for k in p.keywords):
                hits.append(p)
        return hits

    def score(self, p: Part, text: str) -> int:
        t = (text or "").lower()
        return sum(1 for k in p.keywords if k in t)

    def best_match(self, text: str) -> Part | None:
        """Самый специфичный тип детали для лота.

        Берём запись с максимумом совпавших ключевых слов; при равенстве —
        с большим потенциальным содержанием. Это даёт консервативную
        (не завышенную) оценку для лота «однотипных деталей».
        """
        t = (text or "").lower()
        best: Part | None = None
        best_score = 0
        best_val = -1.0
        for p in self.parts:
            if not any(k in t for k in p.keywords):
                continue
            sc = sum(1 for k in p.keywords if k in t)
            val = p.au() + p.pd() * 2 + p.pt() * 2  # грубая веса ценности
            if sc > best_score or (sc == best_score and sc > 0 and val > best_val):
                best = p
                best_score = sc
                best_val = val
        return best


def _f(v) -> float:
    if v is None or v == "":
        return 0.0
    return float(str(v).strip())