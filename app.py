# -*- coding: utf-8 -*-
"""Gold Parser — главный вход.

Примеры запуска:
    python app.py prices                 показать цены ЦБ за грамм
    python app.py calc "КМ-5 конденсаторы партия" -p 3000
    python app.py eval                   вставить лоты построчно (заголовок — цена)
    python app.py import прямо.csv
    python app.py search "микросхемы с золотом"
"""

from __future__ import annotations
import argparse
import csv
import sys
from datetime import datetime
import config
import scraper
from calculator import Lot, Valuation, valuate, format_mg
from prices import CbrError, get_metals
from reference import Reference


def _load():
    config.ensure_dirs()
    try:
        metals = get_metals(allow_cache=True)
    except CbrError as exc:
        sys.exit(f"Ошибка цен ЦБ: {exc}")
    ref = Reference.load()
    print(f"[Цены ЦБ на {metals.asof}]: {metals.summary()}")
    print(f"[Справочник]: загружено {len(ref.parts)} записей о деталях\n")
    return metals, ref


def _make_report(lots: list[Lot], metals, label: str,
                 include_unpriced: bool = False) -> list[Valuation]:
    # в отчёт идут только «содержательные» лоты: есть цена ИЛИ распознана деталь
    kept = [l for l in lots if l.price_rub > 0 or l.parts]
    if include_unpriced:
        vals = [valuate(l, metals) for l in kept]
    else:
        vals = [valuate(l, metals) for l in kept if l.price_rub > 0]

    # таблица
    hdr = (f"{'Источник':14} {'Цена,руб':>10} {'Металл,руб':>11} {'Маржа,руб':>10} "
           f"{'x':>6}  {'Мг Au/Pd/Pt':20} Ссылка / описание")
    print(hdr)
    print("-" * (len(hdr) + 8))
    for v in sorted(vals, key=lambda v: -v.ratio):
        mark = "ВЫГОДНО" if v.is_profitable else ""
        price_txt = f"{v.lot.price_rub:>10,.0f}" if v.lot.price_rub > 0 else "нет цены"
        mgtxt = format_mg(v.mg)
        where = v.lot.url if v.lot.url else v.lot.title[:45]
        print(f"{v.lot.source[:14]:14} {price_txt} {v.metal_value:>11,.0f} "
              f"{v.net:>10,.0f} {v.ratio:>5.1f}x  {mgtxt:20} {where} {mark}")

    prof = [v for v in vals if v.is_profitable]
    print(f"\nВЫГОДНО (металл >= {config.MIN_RATIO:g}x цены и металл >= "
          f"{config.MIN_METAL_VALUE_RUB:g} руб): {len(prof)} из {len(vals)}")

    # CSV
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    out = config.OUTPUT_DIR / f"report_{safe}_{metals.asof}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["source", "title", "url", "price_rub", "metal_value_rub",
                    "net_rub", "ratio_x", "au_mg", "pd_mg", "pt_mg",
                    "profitable", "matched_parts"])
        for v in vals:
            w.writerow([v.lot.source, v.lot.title, v.lot.url,
                        f"{v.lot.price_rub:.2f}".replace(".", ","),
                        f"{v.metal_value:.2f}".replace(".", ","),
                        f"{v.net:.2f}".replace(".", ","),
                        f"{v.ratio:.2f}".replace(".", ","),
                        f"{v.mg.get('au',0):.1f}".replace(".", ","),
                        f"{v.mg.get('pd',0):.1f}".replace(".", ","),
                        f"{v.mg.get('pt',0):.1f}".replace(".", ","),
                        "да" if v.is_profitable else "нет",
                        "; ".join(p.name for p in v.lot.parts)])
    print(f"\nОтчёт сохранён: {out}")
    return vals


def cmd_prices(args, metals, ref):
    print(f"Цены на {metals.asof} (руб/грамм). Только дорогие металлы:")
    for m, name in (("au", "Золото"), ("pd", "Палладий"), ("pt", "Платина")):
        v = metals.prices.get(m)
        if v is not None:
            print(f"  {name:10} {v:>12,.2f}")


def cmd_calc(args, metals, ref):
    best = ref.best_match(args.title)
    lot = Lot(title=args.title, price_rub=args.price, url=args.url or "",
              source="расчёт", parts=[best] if best else [])
    vals = _make_report([lot], metals, f"calc_{args.title[:20]}")
    v = vals[0] if vals else None
    if v is not None:
        print("\nДетали из справочника под объявление:")
        for p in v.lot.parts:
            note = f" — {p.note}" if p.note else ""
            print(f"  • {p.name}: Au={p.au():.1f} Pd={p.pd():.1f} Pt={p.pt():.1f} мг{note}")


def cmd_eval(args, metals, ref):
    print("Вставь лоты построчно (заголовок — цена руб), затем пустая строка + Enter:")
    lines = []
    try:
        while True:
            line = input("> ")
            if not line.strip():
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        pass
    lots = scraper.parse_blob("\n".join(lines), ref)
    if not lots:
        print("Ничего не распознано.")
        return
    _make_report(lots, metals, "eval")


def cmd_import(args, metals, ref):
    lots = scraper.parse_csv(args.file, ref)
    if not lots:
        print("Не распознано ни одного лота.")
        return
    _make_report(lots, metals, args.file.split("\\")[-1].split("/")[-1].rsplit(".", 1)[0])


def cmd_search(args, metals, ref):
    query = args.query
    print(f"Ищу «{query}» по включённым адаптерам площадок...")
    lots = scraper.search_sites(query, ref)
    if not lots:
        print("\nАдаптеров площадок пока не подключено (см. scraper.py), либо всё отрезано антиботом.")
        print("Быстрый путь: найди лоты на Авито/Мешке и вставь их сюда через `eval` или `import`.")
        return
    _make_report(lots, metals, f"search_{query[:20]}")


def cmd_social(args, metals, ref):
    import social
    import social_channels as sc

    tg = {} if args.no_tg else dict(sc.TG_CHANNELS)
    vk = dict(sc.VK_GROUPS)
    if args.channel:
        tg = {args.channel: args.channel}
        vk = {}

    tg = {n: u for n, u in tg.items() if u and not u.startswith("название")}
    vk = {n: u for n, u in vk.items() if u and not u.startswith("название")}

    if not tg and not vk:
        print("Источники не настроены. Открой social_channels.py и добавь "
              "каналы/группы, или передай --channel <имя_телеграм_канала>.")
        return

    lots: list = []
    if tg:
        print(f"Telegram ({len(tg)} канал.): " + ", ".join(tg.values()))
        lots += social.scan_channels(tg, args.limit, ref)
    if vk:
        print(f"VK ({len(vk)} групп): " + ", ".join(vk.values()))
        pages = None
        if args.limit:
            pages = max(1, (args.limit + 19) // 20)
        lots += social.scan_vk_groups(vk, args.limit, ref, token=social.vk_token(),
                                      pages=pages)

    interesting = [l for l in lots if l.parts]
    if not interesting:
        print("За этот проход содержательных сообщений с распознанными деталями не найдено.")
        if lots:
            print("(всего сообщений с ценой/текстом: %d, но тип детали не распознан)" % len(lots))
        return
    _make_report(interesting, metals, "social", include_unpriced=True)


def cmd_shops(args, metals, ref):
    import csv
    import shops
    print("Прайс-листы скупщиков (цены их закупа):")
    items = shops.scan_shops(config.SHOP_SOURCES, args.category)
    if not items:
        print("Ничего не получено (сети нет или разделы изменились).")
        return
    items.sort(key=lambda i: (i.category, i.price_rub))
    print(f"\n{'Категория':12} {'Цена,руб':>11} {'Ед':>3}  Название")
    print("-" * 90)
    for it in items:
        print(f"{it.category:12} {it.price_rub:>11,.2f} {it.unit:>3}  {it.name[:55]}")
    out = config.OUTPUT_DIR / f"shops_{metals.asof}.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["category", "name", "unit", "price_rub", "detail_url"])
        for it in items:
            w.writerow([it.category, it.name, it.unit,
                        f"{it.price_rub:.2f}".replace(".", ","), it.detail_url])
    print(f"\nСохранено: {out}")


def cmd_vksearch(args, metals, ref):
    import social
    token = social.vk_token()
    if not token:
        print("Для поиска по VK нужен токен: VK_TOKEN или data/vk_token.txt "
              "(см. README, раздел «Соцсети»).")
        return
    lots: list = []
    if args.market:
        print(f"VK market.search: «{args.query}»")
        lots = social.vk_search_market(args.query, args.count or 30, ref, token)
    else:
        print(f"VK newsfeed.search (посты): «{args.query}»")
        lots = social.vk_search_posts(args.query, args.count or 30, ref, token)
    interesting = [l for l in lots if l.parts]
    if not interesting:
        print("По запросу содержательных находок с распознанными деталями нет.")
        return
    _make_report(interesting, metals, f"vk_{args.query[:20]}")


def build_parser():
    p = argparse.ArgumentParser(prog="app.py", description="Gold Parser — бот оценки радиодеталей с драгметаллами")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("prices", help="цены ЦБ за грамм")

    c = sub.add_parser("calc", help="оценить один лот")
    c.add_argument("title", help="описание лота")
    c.add_argument("-p", "--price", type=float, required=True, help="цена лота, руб")
    c.add_argument("-u", "--url", help="(опц.) ссылка на объявление")

    sub.add_parser("eval", help="вставить лоты построчно")

    im = sub.add_parser("import", help="импорт CSV (title;price;url)")
    im.add_argument("file", help="путь к CSV")

    s = sub.add_parser("search", help="поиск по площадкам")
    s.add_argument("query", help="поисковый запрос")

    so = sub.add_parser("social", help="сканировать Telegram-каналы и VK-группы")
    so.add_argument("--channel", help="отдельный канал вместо списка из social_channels.py")
    so.add_argument("--limit", type=int, default=None, help="сколько сообщений с каждого источника")
    so.add_argument("--no-tg", action="store_true",
                    help="не обращаться к t.me (если до него нет доступа)")

    sh = sub.add_parser("shops", help="прайс-листы скупщиков радиодеталей")
    sh.add_argument("--category", default=None, help="фильтр по подстроке категории")

    bd = sub.add_parser("boards", help="форумы-барахолки (radiokot)")
    bd.add_argument("--forum", type=int, default=None, help="только один раздел (f-ид)")
    bd.add_argument("--pages", type=int, default=None, help="сколько блоков тем листать")
    bd.add_argument("--slow", action="store_true", help="добавить медленные барахолки (zx-pk, vkupiprodai)")

    mk = sub.add_parser("market", help="парсинг Авито/Мешка/Юлы (curl_cffi + cookies)")
    mk.add_argument("site", choices=["avito", "meshok", "youla"], help="площадка")
    mk.add_argument("query", help="поисковый запрос")
    mk.add_argument("--region", default=None, help="регион (слаг, напр. moskva)")
    mk.add_argument("--limit", type=int, default=None, help="максимум лотов")

    uc = sub.add_parser("uc", help="парсинг площадок через uc-браузер (обход капчи)")
    uc.add_argument("site", choices=["avito", "meshok", "youla"], help="площадка")
    uc.add_argument("query", help="поисковый запрос")
    uc.add_argument("--limit", type=int, default=None, help="максимум лотов")
    uc.add_argument("--dump", action="store_true", help="сохранить HTML дамп")
    uc.add_argument("--pages", default=None, help="глубина: 5/15/40/60/100/150 или 'все'")

    sc_ = sub.add_parser("scan", help="поиск по всем площадкам сразу (Авито+Мешок+Юла)")
    sc_.add_argument("query", help="поисковый запрос")
    sc_.add_argument("--sites", nargs="*", default=None,
                     choices=["avito", "meshok", "youla"], help="площадки (по умолчанию все)")
    sc_.add_argument("--limit", type=int, default=None, help="максимум лотов на площадку")
    sc_.add_argument("--pages", default=None,
                     help="глубина: 5/15/40/60/100/150 или 'все'")

    hu = sub.add_parser("hunt", help="найти всё выгодное: перебор ключей по всем площадкам")
    hu.add_argument("--sites", nargs="*", default=None,
                    choices=["avito", "meshok", "youla"], help="площадки (по умолчанию все)")
    hu.add_argument("--limit", type=int, default=None, help="максимум лотов на площадку на ключ")
    hu.add_argument("--pages", default=None, help="глубина на площадку (5/15/40/60/100/150/'все')")

    st = sub.add_parser("stats", help="статистика из истории найденных лотов")
    st.add_argument("--days", type=int, default=None, help="период в днях (по умолч. вся история)")

    ex = sub.add_parser("export", help="экспорт истории найденных лотов в файл")
    ex.add_argument("--format", default="csv", choices=["csv", "xlsx"], help="формат файла")
    ex.add_argument("--days", type=int, default=None, help="период в днях (по умолч. всё)")

    mo = sub.add_parser("monitor", help="мониторинг: искать новые выгодные лоты постоянно")
    mo.add_argument("--every", type=int, default=None, help="интервал между проходами, сек")
    mo.add_argument("--x", type=float, default=None, help="порог кратности (по умолчаю MIN_RATIO, напр. 5)")
    mo.add_argument("--auto-open", action="store_true", help="автооткрывать выгодные лоты в браузере")
    mo.add_argument("--vk", action="store_true", help="добавить VK (тяжелее, через Chrome)")
    mo.add_argument("--slow", action="store_true", help="добавить медленные барахолки (zx-pk, vkupiprodai)")
    mo.add_argument("--post-to", type=str, default=None,
                    help="ID канала для постинга (free: без ссылки, задержка 3ч)")
    mo.add_argument("--post-to-pro", type=str, default=None,
                    help="ID канала для PRO-постинга (со ссылкой, мгновенно)")

    vs = sub.add_parser("vksearch", help="поиск по VK (нужен токен)")
    vs.add_argument("query", help="поисковый запрос")
    vs.add_argument("--market", action="store_true", help="искать в товарах (с ценой)")
    vs.add_argument("--count", type=int, default=None, help="сколько результатов")

    return p


def _setup_console() -> None:
    """UTF-8 и построчный вывод (корректная кириллица, живой вывод в pipe)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        import io  # noqa: F401
    except Exception:
        pass


def open_in_browser(urls: list[str]) -> None:
    import webbrowser
    for u in urls:
        try:
            webbrowser.open(u)
        except Exception as exc:
            print(f"  не открыл {u}: {exc}")


def _clean_url(u: str) -> str:
    """Убирает из ссылок Авито мусорные параметры (context, slocation и пр.)."""
    if not u:
        return u
    # avito: /.../slug_123?context=...&slocation=...  ->  /.../slug_123
    return u.split("?")[0].split("&")[0]


def _print_good_links(vals: list[Valuation]) -> None:
    """Выводит только выгодные лоты компактными кликабельными ссылками
    и сохраняет список выгодных ссылок в data/good_links.json (для панели)."""
    import json as _json
    good = [v for v in vals if v.is_profitable]
    if not good:
        print("\nВыгодных (металл >= 3x и >= 100 ₽) пока нет.")
        _save_good_links([])
        return
    good.sort(key=lambda v: -v.ratio)
    # сохраняем для панели
    links = []
    for v in good:
        u = _clean_url(v.lot.url)
        if u:
            links.append({"url": u, "ratio": round(v.ratio, 2),
                          "title": (v.lot.title or "").strip()[:60],
                          "metal": round(v.metal_value), "price": round(v.lot.price_rub)})
    _save_good_links(links)
    print(f"\n=== ВЫГОДНЫЕ ({len(good)}) — чистые ссылки ===")
    for v in good:
        title = (v.lot.title or "").strip() or "?"
        print(f"{v.ratio:5.1f}x  {v.metal_value:6,.0f}₽/{v.lot.price_rub:,.0f}₽  |  {title[:45]}")
        print(f"        {_clean_url(v.lot.url)}")


def _save_good_links(links: list[dict]) -> None:
    import json as _json
    try:
        config.ensure_dirs()
        (config.DATA_DIR / "good_links.json").write_text(
            _json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def cmd_hunt(args, metals, ref):
    """«Найти всё выгодное»: перебирает список ключей по всем площадкам."""
    import board_uc
    import scraper
    queries = config.HUNT_QUERIES
    sites = args.sites or config.DEFAULT_SITES
    pages = args.pages or 8
    limit = args.limit or 30
    print(f"[hunt] {len(queries)} ключей × {', '.join(sites)} (один браузер на площадку)")
    rows = []
    for s in sites:
        print(f"\n=== площадка {s} ===", flush=True)
        try:
            raw = board_uc.collect_many(s, queries, limit_per=limit, max_pages=pages)
            print(f"  [{s}] всего собрано: {len(raw)}", flush=True)
            for it in raw:
                lot = scraper.lot_from_text(it.get("title") or "", ref,
                                            source=s, url=it.get("url") or "")
                if it.get("price"):
                    lot.price_rub = float(it["price"])
                # только объявления, где распознана конкретная деталь (с Au/Pd/Pt)
                if lot.parts:
                    rows.append(lot)
        except Exception as e:
            print(f"  [{s}] ошибка: {e}", flush=True)
    print(f"\n[HUNT] всего лотов после фильтра: {len(rows)}")
    if not rows:
        print("Выгодного/содержимого не найдено.")
        return
    # Блок 4: пишем историю всех распознанных лотов
    try:
        import history
        hist = []
        for lot in rows:
            v = valuate(lot, metals)
            hist.append({"title": lot.title, "price": lot.price_rub,
                         "metal_value": v.metal_value, "ratio": v.ratio,
                         "url": lot.url, "site": lot.source or "—", "query": "hunt"})
        n = history.record_scan("hunt", "«все ключи»", hist)
        print(f"  [history] записано лотов: {n}", flush=True)
    except Exception as e:
        print(f"  [history] ошибка записи: {e}", flush=True)
    vals = _make_report(rows, metals, "hunt", include_unpriced=True)
    _print_good_links(vals)


def cmd_stats(args, metals, ref):
    """Сводка из истории: всего лотов, выгодных, ср. ratio, топ-5."""
    import history
    days = args.days
    s = history.stats(days=days)
    period = f"за {days} дн." if days else "за всё время"
    print(f"\n=== СТАТИСТИКА ({period}) ===")
    print(f"Всего лотов в истории: {s['total']}")
    print(f"Выгодных (≥3×): {s['good']}")
    print(f"Средний ratio: {s['avg_ratio']}")
    print("По площадкам: " + ", ".join(f"{b['site']}={b['c']}" for b in s['by_site']))
    print("\nТоп-5 по ratio:")
    for t in s["top"]:
        print(f"  ×{t['ratio']:.1f}  {t['price']:.0f}₽/{(t['metal_value'] or 0):.0f}₽  | {str(t['title'] or '?')[:45]}")


def cmd_export(args, metals, ref):
    """Экспорт истории найденных лотов в файл (csv/xlsx)."""
    import history
    fmt = (args.format or "csv").lower()
    out = config.OUTPUT_DIR / f"history_{datetime.now():%Y%m%d_%H%M}.{fmt}"
    config.ensure_dirs()
    if fmt == "xlsx":
        n = history.to_xlsx(out)
    else:
        n = history.to_csv(out)
    print(f"Экспортировано записей: {n} -> {out}")


def cmd_scan(args, metals, ref):
    """Один запрос по Авито+Мешку+Юле, сводный отчёт со сортировкой по x3."""
    import board_uc
    import scraper
    query = args.query
    sites = args.sites or config.DEFAULT_SITES
    print(f"[scan] запрос=«{query}» по {', '.join(sites)}. "
          f"Если откроется капча — кликни её в окне (пикуется один раз).")
    rows = []
    for s in sites:
        try:
            raw = board_uc.collect_lots(s, query, limit=args.limit or 200,
                                        max_pages=args.pages or 8)
            print(f"  {s}: {len(raw)} лотов", flush=True)
            for it in raw:
                lot = scraper.lot_from_text(it.get("title") or "", ref,
                                            source=s, url=it.get("url") or "")
                if it.get("price"):
                    lot.price_rub = float(it["price"])
                # только объявления, где распознана конкретная деталь (с Au/Pd/Pt)
                if lot.parts:
                    rows.append(lot)
        except Exception as e:
            print(f"  {s}: ошибка {e}", flush=True)
    if not rows:
        print("Ничего не собрано.")
        return
    # Блок 4: пишем историю всех распознанных лотов
    try:
        import history
        hist = []
        for lot in rows:
            v = valuate(lot, metals)
            hist.append({"title": lot.title, "price": lot.price_rub,
                         "metal_value": v.metal_value, "ratio": v.ratio,
                         "url": lot.url, "site": "—", "query": query})
        n = history.record_scan("scan", query, hist)
        print(f"  [history] записано лотов: {n}", flush=True)
    except Exception as e:
        print(f"  [history] ошибка записи: {e}", flush=True)
    vals = _make_report(rows, metals, f"scan_{query[:15]}", include_unpriced=True)
    _print_good_links(vals)


def cmd_uc(args, metals, ref):
    """Парсинг Авито/Юлы/Мешка через uc-браузер (обход капчи однократно)."""
    import board_uc
    import scraper
    site = args.site
    query = args.query
    print(f"[uc] площадка={site}, запрос=«{query}». Если откроется капча 'я не робот' — "
          f"кликни её в окне (пикуется один раз).")
    raw = board_uc.collect_lots(site, query, limit=args.limit or 200, dump=args.dump,
                                        max_pages=args.pages or 8)
    if not raw:
        print("Лотов не получено (капча не пройдена или выдача пуста).")
        return
    lots = []
    for it in raw:
        lot = scraper.lot_from_text(it.get("title") or "", ref, source=f"{site}",
                                    url=it.get("url") or "")
        if it.get("price"):
            lot.price_rub = float(it["price"])
        if lot.price_rub > 0 or lot.parts:
            lots.append(lot)
    vals = _make_report(lots, metals, f"uc_{site}", include_unpriced=True)
    _print_good_links(vals)


def cmd_market(args, metals, ref):
    import market
    site = args.site or "avito"
    query = args.query
    print(f"[market] площадка={site}, запрос=«{query}»")
    try:
        lots = market.scan(site, query, ref, region=args.region,
                           max_items=args.limit or 40)
    except Exception as exc:
        print(f"Ошибка: {exc}")
        print("Подсказка: Авито/Мешок требуют cookies (stealth-браузер) и рабочую "
              "сеть (VPN). Обычно это нужно для живого теста.")
        return
    if not lots:
        print("Лотов не найдено (возможно, блокировка/нет выдачи).")
        return
    _make_report(lots, metals, f"market_{site}", include_unpriced=True)


def cmd_boards(args, metals, ref):
    import boards
    print("Открытые форумы-барахолки:")
    forums = None if not getattr(args, "forum", None) else [int(getattr(args, "forum"))]
    lots = boards.scan_boards(forums, getattr(args, "pages", None), ref,
                              slow=bool(getattr(args, "slow", False)))
    if not lots:
        print("Ничего не распознано.")
        return
    _make_report(lots, metals, "boards", include_unpriced=True)


def _seen_path():
    return config.DATA_DIR / "seen.json"


def _load_seen() -> set[str]:
    import json
    try:
        return set(json.loads(_seen_path().read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_seen(seen: set[str]) -> None:
    import json
    try:
        config.ensure_dirs()
        _seen_path().write_text(
            json.dumps(sorted(s for s in seen if s), ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def beep() -> None:
    """Звуковое уведомление о находке (Windows)."""
    import sys as _sys
    try:
        if _sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.kernel32.Beep(1200, 350)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


def cmd_monitor(args, metals, ref):
    """Мониторинг: периодически проверяет источники и показывает новые выгодные лоты."""
    import time
    import webbrowser
    import social
    import boards
    import social_channels as sc

    seen = _load_seen()
    interval = args.every or config.MONITOR_INTERVAL
    x = args.x or config.MIN_RATIO
    open_after = args.auto_open
    pending_open: list[str] = []
    print(f"Монитор запущен. Проверяю каждые {interval} с. Источники: "
          f"{'Telegram ' if config.MONITOR_ENABLE_TG else ''}"
          f"{'radiokot ' if config.MONITOR_ENABLE_BOARDS else ''}"
          f"{'медл.барахолки ' if args.slow else ''}"
          f"{'VK ' if args.vk else ''}"
          f"| новые выгодные (металл >= {x:g}x цены и >= {config.MIN_METAL_VALUE_RUB:g} руб) "
          f"будут показаны."
          + (" Лучшие автоматически откроются в браузере, если нажать Enter."
             if open_after else " Ctrl+C — выход."))

    def one_pass() -> None:
        nonlocal seen, pending_open
        lots: list = []
        if config.MONITOR_ENABLE_TG:
            try:
                tg = {n: u for n, u in sc.TG_CHANNELS.items()
                      if u and not u.startswith("название")}
                lots += social.scan_channels(tg, 15, ref)
            except Exception as exc:
                print(f"  [monitor] telegram: {exc}")
        if config.MONITOR_ENABLE_BOARDS:
            try:
                lots += boards.scan_boards(ref=ref, pages=1, slow=bool(args.slow))
            except Exception as exc:
                print(f"  [monitor] boards: {exc}")
        if args.vk:
            try:
                vk = {n: u for n, u in sc.VK_GROUPS.items()
                      if u and not u.startswith("название")}
                lots += social.scan_vk_groups(vk, ref=ref, token=social.vk_token())
            except Exception as exc:
                print(f"  [monitor] vk: {exc}")

        new_found = 0
        for l in lots:
            if not (l.url or l.title):
                continue
            key = l.url or l.title
            if key in seen:
                continue
            seen.add(key)
            v = valuate(l, metals)
            if v.is_profitable and v.ratio >= x:
                new_found += 1
                beep()
                print(f"\nНовый выгодный лот · {v.ratio:.1f}x · металл {v.metal_value:,.0f} ₽"
                      f" · цена {v.lot.price_rub:,.0f} ₽")
                print(f"  {v.lot.title}")
                print(f"  {v.lot.url}  [{v.lot.source}]")
                # автопостинг в канал (Блок 3)
                if getattr(args, "post_to", None) or getattr(args, "post_to_pro", None):
                    try:
                        import bot.poster as poster
                        lot_dict = {"title": l.title, "price": l.price_rub,
                                    "metal_value": v.metal_value, "ratio": v.ratio,
                                    "url": l.url}
                        poster.post_lot(lot_dict,
                                        channel_id=getattr(args, "post_to", None),
                                        pro_channel_id=getattr(args, "post_to_pro", None),
                                        is_pro=bool(getattr(args, "post_to_pro", None)))
                    except Exception as exc:
                        print(f"  [monitor] post err: {exc}", flush=True)
                u = l.url
                if u and str(u).startswith("http"):
                    pending_open.append(u)
        if new_found:
            _save_seen(seen)
            print(f"  — новых выгодных в этом проходе: {new_found}")
            if open_after:
                # собираем и открываем накопившиеся ссылки
                if pending_open:
                    print("  Открываю в браузере...")
                    for u in pending_open[:3]:
                        try:
                            webbrowser.open(u)
                        except Exception:
                            pass
                    pending_open = []
        else:
            print(f"  [{time.strftime('%H:%M:%S')}] новых выгодных нет.")

    # первый проход сразу, дальше по таймеру
    print()
    try:
        while True:
            one_pass()
            time.sleep(interval)
    except KeyboardInterrupt:
        _save_seen(seen)
        print("\nМонитор остановлен.")


def cmd_best(metals, ref):
    """Сканирует VK + барахолку и открывает выгодные лоты в браузере для покупки."""
    import social
    import boards
    import social_channels as sc
    vk = {n: u for n, u in sc.VK_GROUPS.items() if u and not u.startswith("название")}
    print("Сканирую VK-группы и форумы-барахолки, ищу выгодные лоты "
          f"(металл >= {config.MIN_RATIO:g}x цены и металл >= {config.MIN_METAL_VALUE_RUB:g} руб)...")
    lots_vk = social.scan_vk_groups(vk, ref=ref, token=social.vk_token())
    lots_bd = boards.scan_boards(ref=ref)
    lots = lots_vk + lots_bd
    vals = [valuate(l, metals) for l in lots]
    good = [v for v in vals if v.is_profitable and v.lot.url]
    good.sort(key=lambda v: -v.ratio)
    if not good:
        print("\nСейчас выгодных лотов со ссылкой не нашлось. "
              "Попробуй позже (объявления появляются постоянно).")
        return
    print(f"\nНайдено выгодных: {len(good)}")
    for i, v in enumerate(good, 1):
        print(f"{i:2}. {v.ratio:.1f}x | маржа {v.net:,.0f} руб | {v.lot.title[:38]}")
        print(f"     {v.lot.url}")
    ans = _ask("\nОткрыть их в браузере для покупки? (сколько первых, Enter=все, 0=нет): ")
    if ans == "0":
        return
    n = None
    if ans:
        try:
            n = int(ans)
        except ValueError:
            n = len(good)
    if n is None:
        n = len(good)
    open_in_browser([v.lot.url for v in good[:n]])
    print("Открыл в браузере.")


def _ask(question: str, default: str = "") -> str:
    try:
        return input(question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""


def _pause() -> None:
    _ask("\nНажми Enter, чтобы вернуться в меню...")


def menu(metals, ref):
    import argparse as _a

    print("\n" + "=" * 60)
    print("  GOLD PARSER — меню")
    print("=" * 60)
    while True:
        print("""
  1. Цены драгметаллов (ЦБ РФ за грамм)
  2. Прайсы скупщиков (что платят за детали)
  3. Сканировать VK-группы и Telegram-каналы
  4. Оценить один лот (описание + цена)
  5. Ввести лоты вручную (накопировать с сайта)
  6. Импорт лотов из CSV-файла
  7. Самопроверка (тесты)
  8. Куда смотреть отчёты и настройки
  9. Найти выгодные лоты и открыть в браузере для покупки
 10. Форум-барахолка radiokot (объявления о продаже)
 11. Монитор: ловить новые выгодные объявления (Ctrl+C — выход)
  0. Выход""")
        c = _ask("\nВыбери пункт (0-11): ")
        if c == "0":
            print("До свидания!")
            return
        if c == "1":
            cmd_prices(_a.Namespace(), metals, ref); _pause()
        elif c == "2":
            cmd_shops(_a.Namespace(category=None), metals, ref); _pause()
        elif c == "3":
            no_tg = not (_ask("Telegram доступен? (у тебя только через VPN) [да/Нет]: ") in ("y", "д", "да", "1"))
            limit = 60 if _ask("Подгрузить больше постов со стен VK (~60) [да/Нет]: ") in ("y", "д", "да", "1") else None
            cmd_social(_a.Namespace(channel=None, limit=limit, no_tg=no_tg), metals, ref)
            _pause()
        elif c == "4":
            title = _ask("Описание лота: ")
            price = _ask("Цена (руб): ")
            try:
                p = float(price.replace(",", "."))
            except ValueError:
                print("Цену не понял, пропускаю.")
                p = None
            if title and p is not None:
                cmd_calc(_a.Namespace(title=title, price=p, url=""), metals, ref)
            _pause()
        elif c == "5":
            cmd_eval(_a.Namespace(), metals, ref); _pause()
        elif c == "6":
            fn = _ask("Путь к CSV-файлу (например sample_lots.csv): ")
            if fn:
                cmd_import(_a.Namespace(file=fn), metals, ref)
            _pause()
        elif c == "7":
            import subprocess
            subprocess.run([sys.executable, "tests.py"])
            _pause()
        elif c == "8":
            print(f"""
  Отчёты:     {config.OUTPUT_DIR}
  Кэш цен:    {config.CACHE_PRICES}
  Ручная цена: {config.MANUAL_PRICES} (шаблон в manual_prices.example.json)
  Справочник деталей: {config.COMPONENTS_CSV}
  Источники (группы/каналы): social_channels.py
  Пороги «металл >= N× цены» и мин. стоимости металла: config.py (MIN_RATIO, MIN_METAL_VALUE_RUB)""")
            _pause()
        elif c == "9":
            cmd_best(metals, ref)
            _pause()
        elif c == "10":
            cmd_boards(_a.Namespace(forum=None, pages=None), metals, ref)
            _pause()
        elif c == "11":
            x = _ask("Порог кратности (Enter=3, или 5/10 для только топ): ")
            try:
                xv = float(x) if x else None
            except ValueError:
                xv = None
            ao = _ask("Автоматически открывать выгодные в браузере [да/Нет]: ") in ("y", "д", "да", "1")
            cmd_monitor(_a.Namespace(every=None, x=xv, auto_open=ao, vk=False, slow=False),
                        metals, ref)
        else:
            print("Такого пункта нет.")


def main():
    _setup_console()
    args = build_parser().parse_args()

    if args.cmd is None:
        metals, ref = _load()
        menu(metals, ref)
        return

    if args.cmd == "prices":
        config.ensure_dirs()
        try:
            metals = get_metals(allow_cache=not getattr(args, "fresh", False))
        except CbrError as exc:
            sys.exit(f"Ошибка цен ЦБ: {exc}")
        ref = Reference.load()  # не нужен, но симметрично
        cmd_prices(args, metals, ref)
        return

    metals, ref = _load()
    if args.cmd == "calc":
        cmd_calc(args, metals, ref)
    elif args.cmd == "eval":
        cmd_eval(args, metals, ref)
    elif args.cmd == "import":
        cmd_import(args, metals, ref)
    elif args.cmd == "search":
        cmd_search(args, metals, ref)
    elif args.cmd == "social":
        cmd_social(args, metals, ref)
    elif args.cmd == "shops":
        cmd_shops(args, metals, ref)
    elif args.cmd == "boards":
        cmd_boards(args, metals, ref)
    elif args.cmd == "market":
        cmd_market(args, metals, ref)
    elif args.cmd == "uc":
        cmd_uc(args, metals, ref)
    elif args.cmd == "scan":
        cmd_scan(args, metals, ref)
    elif args.cmd == "hunt":
        cmd_hunt(args, metals, ref)
    elif args.cmd == "stats":
        cmd_stats(args, metals, ref)
    elif args.cmd == "export":
        cmd_export(args, metals, ref)
    elif args.cmd == "monitor":
        cmd_monitor(args, metals, ref)
    elif args.cmd == "vksearch":
        cmd_vksearch(args, metals, ref)


if __name__ == "__main__":
    main()