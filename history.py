# -*- coding: utf-8 -*-
"""История найденных лотов (SQLite data/history.db) и статистика.

Пишем ВСЕ найденные лоты (не только выгодные), чтобы можно было показать
клиенту: сколько найдено, сколько выгодных, средний ratio, топ по ratio.

Команды app.py:
  stats            — сводка из истории (за период)
  export --xlsx    — выгрузка истории в Excel
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
HISTORY_DB = BASE / "data" / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT,
    query TEXT,
    title TEXT,
    price REAL,
    metal_value REAL,
    ratio REAL,
    url TEXT,
    scanned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_at ON scans(scanned_at);
CREATE INDEX IF NOT EXISTS idx_ratio ON scans(ratio);
"""


def _conn():
    BASE.joinpath("data").mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(HISTORY_DB))
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    with _conn() as con:
        con.executescript(SCHEMA)


def record_scan(site: str, query: str, lots: list[dict]) -> int:
    """Пишет пачку лотов в историю. Возвращает число записей."""
    init()
    now = datetime.now().isoformat(timespec="seconds")
    rows = []
    for lot in lots[:2000]:
        rows.append((site, query, lot.get("title"), lot.get("price"),
                     lot.get("metal_value"), lot.get("ratio"), lot.get("url"), now))
    with _conn() as con:
        con.executemany(
            "INSERT INTO scans(site, query, title, price, metal_value, ratio, url, scanned_at)"
            " VALUES(?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def stats(days: int | None = None) -> dict:
    """Общая статистика. days=None — вся история."""
    init()
    where = ""
    params = []
    if days:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        where = "WHERE scanned_at >= ?"
        params = [since]
    with _conn() as con:
        total = con.execute(f"SELECT COUNT(*) c FROM scans {where}", params).fetchone()["c"]
        good_where = (where + " AND") if where else "WHERE"
        good = con.execute(f"SELECT COUNT(*) c FROM scans {good_where} ratio>=3", params).fetchone()["c"]
        avg = con.execute(f"SELECT AVG(ratio) a FROM scans {where}", params).fetchone()["a"] or 0
        top = con.execute(
            f"SELECT title, price, metal_value, ratio, url, scanned_at FROM scans {where}"
            " ORDER BY ratio DESC LIMIT 5", params).fetchall()
        by_site = con.execute(
            f"SELECT site, COUNT(*) c FROM scans {where} GROUP BY site ORDER BY c DESC", params).fetchall()
    return {
        "total": total, "good": good,
        "avg_ratio": round(float(avg), 2),
        "top": [dict(r) for r in top],
        "by_site": [dict(r) for r in by_site],
    }


def query_history(query_filter: str | None = None, days: int | None = None) -> list[dict]:
    """Выборка записей истории (для экспорта)."""
    init()
    where = []
    params = []
    if query_filter:
        where.append("query LIKE ?")
        params.append(f"%{query_filter}%")
    if days:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        where.append("scanned_at >= ?")
        params.append(since)
    sql = "SELECT site, query, title, price, metal_value, ratio, url, scanned_at FROM scans"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY ratio DESC"
    with _conn() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def to_csv(path: Path) -> int:
    """Экспорт истории в CSV (все записи)."""
    import csv
    rows = query_history()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["site", "query", "title", "price",
                                           "metal_value", "ratio", "url", "scanned_at"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return len(rows)


def to_xlsx(path: Path) -> int:
    """Экспорт истории в XLSX (openpyxl)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    rows = query_history()
    wb = Workbook()
    ws = wb.active
    ws.title = "История"
    headers = ["Площадка", "Запрос", "Название", "Цена", "Металл", "Ratio", "Ссылка", "Дата"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r["site"], r["query"], r["title"], r["price"],
                   r["metal_value"], r["ratio"], r["url"], r["scanned_at"]])

    # автоширина
    for col in ws.columns:
        width = max((len(str(c.value or "")) for c in col), default=8) + 2
        ws.column_dimensions[col[0].column_letter].width = min(width, 60)
    wb.save(path)
    return len(rows)