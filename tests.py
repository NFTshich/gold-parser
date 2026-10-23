# -*- coding: utf-8 -*-
"""Самопроверка без интернета: справочник, калькулятор, парсинг лотов.

Запуск:  python tests.py
"""

from __future__ import annotations

from calculator import Lot, valuate
from prices import Metals
from reference import Reference
import json
import scraper

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} {detail}")


def test_reference():
    print("\n[1] Справочник")
    ref = Reference.load()
    check("загружено kм и палладиевых конденсаторов",
          any(p.name.startswith("КМ-") and p.pd() > 0 for p in ref.parts))
    check("есть золотые микросхемы", any(p.au() > 0 for p in ref.parts))
    hit = ref.match_by_text("Конденсаторы КМ-5 с палладием, партия")
    check("поиск по тексту находит КМ", any(p.name.startswith("КМ-5") for p in hit),
          str([p.name for p in hit]))
    hit = ref.match_by_text("радиостанция бортовая рация на разбор")
    check("рация распознаётся", any("рация" in p.name or "Радиостанция" == p.name for p in hit),
          str([p.name for p in hit]))


def test_blob_parse():
    print("\n[2] Парсинг вводимых лотов")
    ref = Reference.load()
    blob = (
        "Конденсаторы КМ-5 палладий 100шт — 4000 руб\n"
        "https://meshok.example/item/1  Микросхемы К134 с золотом 30шт 2500.\n"
        "Рация старая бортовая, платы с позолотой — 6000руб"
    )
    lots = scraper.parse_blob(blob, ref)
    check("распознано 3 лота", len(lots) == 3, f"{len(lots)}")
    price_ok = all(l.price_rub in (4000.0, 2500.0, 6000.0) for l in lots)
    check("цены извлечены из '— 4000 руб' и '2500.'", price_ok,
          str([l.price_rub for l in lots]))
    matched = all(l.parts for l in lots)
    check("по каждому лоту подобраны детали из справочника", matched,
          str([[p.name for p in l.parts] for l in lots]))


def test_price_labels():
    print("\n[2b] Распознавание цены с метками")
    cases = {
        "Цена: 44.000": 44000.0,
        "за 2000 р": 2000.0,
        "Цена 15 000 руб": 15000.0,
        "Продаю телевизор, цена 3,500 рублей": 3500.0,
    }
    for txt, exp in cases.items():
        got, _ = scraper._extract_price(txt)
        check(f"'{txt[:30]}' -> {exp:g}", abs(got - exp) < 0.01, f"got {got}")


def test_calculator():
    print("\n[3] Калькулятор маржи")
    metals = Metals({"au": 7200.0, "pd": 3100.0, "pt": 2900.0}, "2026-09-28", source="тест")
    # Золото: 0.200 г = 200 мг * 7200 руб/г = 1440 руб
    gold = Reference.load().match_by_text("КМ-5")  # не важно, возьмём известные
    ref = Reference.load()
    # синтетический лот: 40 мг Au
    class P:
        def __init__(s, mg): s.mg = mg
        def mg_by_metal(s): return {"au": s.mg, "pd": 0.0, "pt": 0.0}
    lot = Lot(title="тест", price_rub=100.0, parts=[P(200.0)])
    v = valuate(lot, metals)  # 200 мг Au=0.2 г → 0.2*7200=1440
    check("200 мг Au = 1440 руб", abs(v.metal_value - 1440.0) < 0.01, f"{v.metal_value}")
    check("раз 14.4 (металл в 14.4x цены)", abs(v.ratio - 14.4) < 0.01, f"{v.ratio}")
    check("маржа 1340 руб", abs(v.net - 1340.0) < 0.01, f"{v.net}")
    check("лот выгоден (>=3x, >=500р)", v.is_profitable, f"{v.ratio:.2f}x {v.net}")

    # невыгодный: 50 мг Au = 360 руб, цена 400 → ratio 0.9
    lot2 = Lot(title="тест2", price_rub=400.0, parts=[P(50.0)])
    v2 = valuate(lot2, metals)
    check("невыгодный лот не проходит", not v2.is_profitable,
          f"{v2.ratio:.2f}x {v2.net}")


def test_report_csv():
    print("\n[4] Итоговый отчёт (вывод таблицы из app.py через вызов)")
    # проверяем, что pipeline из 3 лотов собирается в valuations
    ref = Reference.load()
    metals = Metals({"au": 7200.0, "pd": 3100.0, "pt": 2900.0}, "тест", "тест")
    lots = [
        Lot(title="КМ-5 конденсаторы 100шт", price_rub=4000, parts=ref.match_by_text("КМ-5")),
        Lot(title="Разъёмы СНЦ с позолотой 20шт", price_rub=1500, parts=ref.match_by_text("разъёмы СНЦ")),
        Lot(title="Плата с ГП золото", price_rub=300, parts=ref.match_by_text("плата с прослотой")),
    ]
    vals = [valuate(l, metals) for l in lots if l.price_rub > 0]
    check("посчитаны все лоты", len(vals) == 3, f"{len(vals)}")
    check("разъём СНЦ найден в балансе", any(v.mg.get("au", 0) > 0 for v in vals))


def test_social_telegram():
    print("\n[5] Парсер Telegram (фикстура t.me/s)")
    from social import TelegramAdapter
    from reference import Reference as R
    ref = R.load()
    fixture = "\n".join([
        '<div class="tgme_widget_message">',
        '  <a class="tgme_widget_message_date" href="/s/chan/11"><time>28 Sep</time></a>',
        '  <div class="tgme_widget_message_text">Продам конденсаторы КМ-5 палладий 100шт за 4000 руб</div>',
        '</div>',
        '<div class="tgme_widget_message">',
        '  <a class="tgme_widget_message_date" href="/s/chan/22"><time>28 Sep</time></a>',
        '  <div class="tgme_widget_message_text">Микросхемы К134 с золотом 50шт. Цена 2500. Самовывоз.</div>',
        '</div>',
        '<div class="tgme_widget_message">',
        '  <a class="tgme_widget_message_date" href="/s/chan/33"><time>28 Sep</time></a>',
        '  <div class="tgme_widget_message_text"><b>Реклама</b></div>',
        '</div>',
    ])
    a = TelegramAdapter("chan")
    lots = a.parse_messages(fixture, 40, ref)
    check("распознано 2 содержательных сообщения", len(lots) == 2, f"{len(lots)}")
    if lots:
        check("у КМ-5 ушла цена 4000", lots[0].price_rub == 4000.0, f"{lots[0].price_rub}")
        check("количество КМ = 100шт", lots[0].qty == 100, f"{lots[0].qty}")
        check("у КМ подобран палладиевый конденсатор", any("КМ" in p.name for p in lots[0].parts),
              str([p.name for p in lots[0].parts]))
        check("ссылка на сообщение собрана", lots[0].url == "https://t.me/chan/11", lots[0].url)


def test_social_vk():
    print("\n[6] Парсер стены VK (фикстура ответа API)")
    from social import VkAdapter
    from reference import Reference as R
    ref = R.load()
    items = [
        {"id": 100, "text": "Продам конденсаторы КМ-5 палладий 200шт за 8000 руб"},
        {"id": 101, "text": "Микросхемы К134 с золотом 40шт. Цена 3000 руб."},
        {"id": 102, "text": "Только фото, без текста"},
        {"id": 103, "text": "Куплю реле с золотыми контактами, до 20 руб/шт"},
    ]
    lots = VkAdapter.parse_wall(items, ref, owner=-12345)
    check("распознано 2 содержательных лота (купля-заявка отсечена)", len(lots) == 2,
          f"{len(lots)}")
    if lots:
        check("цена КМ-5 = 8000", any(l.price_rub == 8000.0 for l in lots),
              str([l.price_rub for l in lots]))
        check("у КМ подобран палладиевый конденсатор",
              any(any("КМ" in p.name for p in l.parts) for l in lots))
        check("url собран как vk.com/wall-12345_100",
              any(l.url == "https://vk.com/wall-12345_100" for l in lots),
              str([l.url for l in lots]))


def test_shops():
    print("\n[7] Прайс-лист скупщика (фикстура каталога)")
    from shops import ShopParser, parse_currency
    check("число '120 388,99 руб.' -> 120388.99",
          abs(parse_currency("120 388,99 руб.") - 120388.99) < 0.001,
          f"{parse_currency('120 388,99 руб.')}")
    check("число '1 560,00  руб.' -> 1560.0",
          abs(parse_currency("1 560,00  руб.") - 1560.0) < 0.001)
    fixture = ("<div class='js_shop shop-item shop'>"
               "<span class='info'> КМ 5 D зелёные</span>"
               "<span class='price'><span class='edizm'>Цена за кг.</span>"
               "<span class='price_num'>144 564,63 руб.</span></span>"
               "<a class='shop-item-title link' href='/km5'>подробнее</a>"
               "</div>"
               "<div class='js_shop shop-item shop'>"
               "<span class='info'>ЭТО-2 крупные</span>"
               "<span class='price'><span class='edizm'>Цена за шт.</span>"
               "<span class='price_num'>331,87 руб.</span></span>"
               "</div>")
    items = ShopParser().parse(fixture, "конденсаторы")
    check("распознано 2 карточки", len(items) == 2, f"{len(items)}")
    if len(items) == 2:
        check("первая — цена за кг 144564.63", items[0].unit == "кг"
              and abs(items[0].price_rub - 144564.63) < 0.01,
              f"{items[0].unit} {items[0].price_rub}")
        check("вторая — цена за шт 331.87", items[1].unit == "шт"
              and abs(items[1].price_rub - 331.87) < 0.01,
              f"{items[1].unit} {items[1].price_rub}")
        check("url детали извлечён", items[0].detail_url == "/km5")


def test_vkbrowser():
    print("\n[8] Парсер отрендеренной стены VK (фикстура DOM)")
    from vkbrowser import parse_wall_posts, discover_owner
    from reference import Reference as R
    ref = R.load()
    fixture = (
        '<div class="post_content"><div class="wall_text">'
        '<div id="wpt-109505426_10" class="wall_post_cont">'
        'Продам конденсаторы КМ-5 палладий 200шт за 8000 руб'
        '</div></div></div>'
        '<div class="post_content"><div class="wall_text">'
        '<div id="wpt-109505426_11" class="wall_post_cont">'
        'Микросхемы К134 с золотом 40шт. Цена 3000 руб.</div></div></div>'
        '<div class="post_content"><div class="wall_text">'
        '<div id="wpt-109505426_12" class="wall_post_cont">Только фото</div>'
        '</div></div>'
    )
    lots = parse_wall_posts(fixture, ref, "vk:test")
    check("распознано 2 содержательных поста", len(lots) == 2, f"{len(lots)}")
    if lots:
        check("цена КМ-5 = 8000", any(l.price_rub == 8000.0 for l in lots),
              str([l.price_rub for l in lots]))
        check("url стены собран", any(l.url == "https://vk.com/wall109505426_10" for l in lots),
              str([l.url for l in lots]))
    check("owner id найден", discover_owner(fixture) == 109505426,
          f"{discover_owner(fixture)}")


def test_boards():
    print("\n[9] Парсер форума-барахолки (фикстура phpBB)")
    from boards import PhpBBAdapter
    from reference import Reference as R
    ref = R.load()
    fixture = (
        '<a href="viewtopic.php?t=77979&sid=abc">Продаю конденсаторы КМ-5 палладий 100шт за 2000</a>'
        '<a href="viewtopic.php?t=123&sid=xyz">Микросхемы К134 с золотом, цена 3000 руб</a>'
        '<a href="viewtopic.php?t=100&sid=q">Просто разговор без цены</a>'
    )
    class Fake(PhpBBAdapter):
        def fetch_topics(self, forum_id, start):
            from bs4 import BeautifulSoup
            s = BeautifulSoup(fixture, "html.parser")
            return [(self.clean_url(a["href"]), a.get_text(" ", strip=True))
                    for a in s.select('a[href*="viewtopic.php?t="]')]
    lots = Fake().scan_forum(42, 1, ref)
    check("распознано 2 содержательных лота", len(lots) == 2, f"{len(lots)}")
    if lots:
        check("цена КМ-5 = 2000", any(l.price_rub == 2000.0 for l in lots),
              str([l.price_rub for l in lots]))
        check("sid убран из ссылки", all("sid" not in l.url for l in lots),
              str([l.url for l in lots]))
        check("ссылка ведёт на тему", any("viewtopic.php?t=" in l.url for l in lots),
              str([l.url for l in lots]))


def test_market_parse():
    print("\n[9b] Парсер Авито (JSON mime/invalid + item_to_lot)")
    from market import find_json_on_page, iter_json_items, item_to_lot
    from reference import Reference as R
    ref = R.load()
    inner = {
        "i18n": {"hasMessages": True},
        "loaderData": {"data": {"catalog": {"items": [
            {"title": "Конденсаторы КМ-5 палладий 100шт",
             "priceDetailed": {"value": {"string": "4000 руб."}},
             "urlPath": "/item/123"}
        ]}}},
    }
    body = json.dumps(inner, ensure_ascii=False).replace("<", "\\u003c")
    fixture = f'<script type="mime/invalid" data-mfe-state="true">{body}</script>'
    data = find_json_on_page(fixture)
    check("JSON извлечён из mime/invalid", data is not None)
    items = iter_json_items(data) if data else []
    check("найдено 1 объявление", len(items) == 1, f"{len(items)}")
    if items:
        lot = item_to_lot(items[0], ref, source="test", url_base="https://www.avito.ru")
        check("цена извлечена 4000", lot and lot.price_rub == 4000.0,
              str(lot.price_rub if lot else None))
        check("url собран avito.ru", lot and "avito.ru" in lot.url,
              str(lot.url if lot else ""))


def test_unrelated_filter():
    print("\n[2c] Отсев нерелевантного (кроссовки/одежда и т.п.)")
    ref = Reference.load()
    good = scraper.lot_from_text("Конденсаторы КМ-5 палладий 100шт за 2000 руб", ref)
    check("реальный лот сохраняется", good.parts and good.price_rub > 0,
          f"{good.price_rub} {len(good.parts)}")
    bad1 = scraper.lot_from_text("Кроссовки Nike новые 3000 руб", ref)
    check("кроссовки отсечены", not bad1.parts and bad1.price_rub == 0,
          f"{bad1.price_rub} {len(bad1.parts)}")
    bad2 = scraper.lot_from_text("Джинсы Levi's размер 48, 1500 руб", ref)
    check("джинсы отсечены", not bad2.parts and bad2.price_rub == 0,
          f"{bad2.price_rub} {len(bad2.parts)}")
    bad3 = scraper.lot_from_text("Пальто женское 5000 руб", ref)
    check("пальто отсеченo", not bad3.parts and bad3.price_rub == 0,
          f"{bad3.price_rub} {len(bad3.parts)}")
    # слово «плата» в «оплата картой» не должно давать ложный матч на плату с позолотой
    tricky = scraper.lot_from_text("Оплата картой через СБП без комиссии", ref)
    check("«оплата» не матчит «плату»", not any(p.name and "позолот" in p.name for p in tricky.parts),
          str([p.name for p in tricky.parts]))


def test_market_proxy():
    print("\n[10b] Парсер прокси-строк")
    from market import parse_proxy
    cases = {
        "1.2.3.4:8080": {"scheme": "http", "host": "1.2.3.4:8080"},
        "user:pass@1.2.3.4:8080": {"scheme": "http", "host": "1.2.3.4:8080",
                                   "username": "user", "password": "pass"},
        "1.2.3.4:8080:user:pass": {"scheme": "http", "host": "1.2.3.4:8080",
                                   "username": "user", "password": "pass"},
        "http://1.2.3.4:8080": {"scheme": "http", "host": "1.2.3.4:8080"},
        "socks5://1.2.3.4:1080": {"scheme": "socks5", "host": "1.2.3.4:1080"},
        "": None,
    }
    for raw, exp in cases.items():
        got = parse_proxy(raw)
        if exp is None:
            check(f"'{raw}' -> None", got is None, f"{got}")
        else:
            check(f"'{raw}'", got and got.get("scheme") == exp["scheme"]
                  and got.get("host") == exp["host"]
                  and got.get("username") == exp.get("username")
                  and got.get("password") == exp.get("password"),
                  f"{got}")


def test_vkupiprodai():
    print("\n[10] Парсер агрегатора объявлений vkupiprodai (фикстура карточек)")
    from boards import VkupiAdapter
    from reference import Reference as R
    ref = R.load()
    fixture = (
        '<div class="list_item margin_bottom_30">'
        '<a class="list_title" href="https://msk.vkupiprodai.ru/office/x_9069429">'
        'Продам конденсаторы КМ-5 палладий, 100шт</a>'
        '<span class="list_price">2 000 ₽</span>'
        '<p class="list_text">Пересылка из Москвы. и радиодетали б/у.</p>'
        '</div>'
        '<div class="list_item margin_bottom_30">'
        '<a class="list_title" href="https://spb.vkupiprodai.ru/office/y_777">'
        'Куплю радиодетали, платы с золотом</a>'
        '<span class="list_price">50 ₽</span>'
        '<p class="list_text">недорого</p>'
        '</div>'
    )
    lots = VkupiAdapter.parse_cards(fixture, ref, "vkupiprodai")
    check("распознано 1 содержательное объявление (купля-заявка отсечена)",
          len(lots) == 1, f"{len(lots)}")
    if lots:
        l = lots[0]
        check("цена 2000 распознана", l.price_rub == 2000.0, f"{l.price_rub}")
        check("ссылка на объявление", "vkupiprodai.ru/office" in l.url, l.url)
        check("деталь КМ подобрана", any("КМ" in p.name for p in l.parts),
              str([p.name for p in l.parts]))


def test_block1():
    print("\n[11] Блок 1: прокси/капча/задержки/ротация")
    import config as cfg
    import board_uc as b
    # прокси по умолчанию пуст, читается из файла
    check("load_uc_proxy() пуст (нет файла)", cfg.load_uc_proxy() == "", cfg.load_uc_proxy())
    # solve_captcha без ключа -> False (заглушка)
    check("solve_captcha off без ключа", b.solve_captcha(None) is False)
    # human_delay в диапазоне [2.5, 6.0] и не блокирует
    import time
    t0 = time.time()
    b.human_delay(0.05, 0.1)
    dt = time.time() - t0
    check("human_delay не ждёт вечно", dt < 5.0, f"{dt:.2f}")
    # _build_driver вызывается (проверка сигнатуры, браузер не запускаем)
    check("_build_driver определена", callable(getattr(b, "_build_driver", None)))
    # CF_MARKERS корректные русские маркеры капчи
    check("CF_MARKERS содержит 'вы не робот'", any("вы не робот" in m for m in b.CF_MARKERS),
          str(b.CF_MARKERS))
    # _is_youla_lot отсеивает города
    check("youla город не лот", b._is_youla_lot("https://youla.ru/sankt-peterburg") is False)
    check("youla лот с id - да", b._is_youla_lot("https://youla.ru/sankt-peterburg/elektronika/mikroshema_123") is True)


def test_block2():
    print("\n[12] Блок 2: база подписчиков и лимиты")
    import bot.db as d
    # тест на временной БД, чтобы не трогать реальную
    import tempfile, pathlib, json
    tmp = pathlib.Path(tempfile.mkdtemp()) / "users_test.db"
    old = d.DB_PATH
    d.DB_PATH = tmp
    try:
        d.init()
        u = d.ensure_user(999001)
        check("пользователь создан free", u["tariff"] == "free", str(u))
        d.set_tariff(999001, "pro", days=30)
        check("pro активен", d.is_active(999001) is True)
        d.set_tariff(999001, "pro", days=0)
        check("pro истёк при 0 дней", d.is_active(999001) is False)
        d.set_tariff(999001, "pro", days=None)
        check("pro бессрочный активен", d.is_active(999001) is True)
        # free: 3 сигнала/день
        d.set_tariff(999001, "free", days=None)
        for i in range(d.FREE_DAILY_LIMIT):
            d.add_signal(999001, {"title": f"лот{i}", "price": 10, "metal_value": 100,
                                  "ratio": 10, "url": f"http://x/{i}"})
        ok, why = d.can_send(999001)
        check("free исчерпал дневной лимит", ok is False, why)
        check("сигналов записано", len(d.recent_good(999001, 5)) == 3,
              str(len(d.recent_good(999001, 5))))
        st = d.all_stats()
        check("статистика считает сигналы", st["signals"] >= 3, str(st))
    finally:
        d.DB_PATH = old


def test_block3():
    print("\n[13] Блок 3: автопостинг в канал")
    import bot.poster as p
    # формат текста
    lot = {"title": "Микросхемы К155", "price": 10, "metal_value": 332,
           "ratio": 33.2, "url": "https://avito.ru/x"}
    t = p.make_text(lot, with_link=True)
    check("текст сигнала со ссылкой", "avito.ru" in t and "×33.2" in t, t[:60])
    tf = p.make_text(lot, with_link=False)
    check("текст free без ссылки", "avito.ru" not in tf)
    # анти-дубль: с временной БД для posted.json
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp()) / "posted.json"
    old = p.POSTED
    p.POSTED = tmp
    try:
        check("сначала не запостено", p.already_posted(lot) is False)
        p.mark_posted(lot)
        check("после mark_posted запостено", p.already_posted(lot) is True)
        # lot_key стабилен
        check("lot_key стабилен", p.lot_key(lot) == p.lot_key(lot))
    finally:
        p.POSTED = old


def test_block4():
    print("\n[14] Блок 4: история и экспорт")
    import history as h
    import tempfile, pathlib
    tmp = pathlib.Path(tempfile.mkdtemp())
    old_db, old_out = h.HISTORY_DB, None
    h.HISTORY_DB = tmp / "history_test.db"
    try:
        h.init()
        lots = [
            {"title": "A", "price": 10, "metal_value": 332, "ratio": 33.2, "url": "http://a"},
            {"title": "B", "price": 50, "metal_value": 100, "ratio": 2.0, "url": "http://b"},
        ]
        n = h.record_scan("avito", "тест", lots)
        check("записано 2 лота", n == 2, str(n))
        s = h.stats()
        check("выгодных 1 (ratio>=3)", s["good"] == 1, str(s))
        check("средний ratio", abs(s["avg_ratio"] - 17.6) < 0.01, str(s["avg_ratio"]))
        # экспорт xlsx
        x = tmp / "hist.xlsx"
        nx = h.to_xlsx(x)
        check("xlsx записан", nx == 2 and x.exists(), str(nx))
    finally:
        h.HISTORY_DB = old_db


def test_block5():
    print("\n[15] Блок 5: расширенный справочник")
    from reference import Reference
    from collections import Counter
    r = Reference.load()
    n = len(r.parts)
    check("позиций >= 150", n >= 150, str(n))
    check("есть кошки доверия", set(p.confidence for p in r.parts) <= {"exact", "estimate", "wide"})
    # ключевые новые детали находятся по названию
    check("КМ-5 Н90 находится", any("КМ-5" in p.name for p in r.match_by_text("конденсаторы КМ-5 Н90")))
    check("КТ907 находится", any("КТ907" in p.name or "КТ907" in p.name for p in r.match_by_text("транзистор КТ907")))
    check("2РМ разъём находится", any("2РМ" in p.name for p in r.match_by_text("разъём 2РМ")))


def main():
    print("Gold Parser — самопроверка")
    test_reference()
    test_blob_parse()
    test_price_labels()
    test_unrelated_filter()
    test_calculator()
    test_report_csv()
    test_social_telegram()
    test_social_vk()
    test_shops()
    test_vkbrowser()
    test_boards()
    test_market_parse()
    test_market_proxy()
    test_vkupiprodai()
    test_block1()
    test_block2()
    test_block3()
    test_block4()
    test_block5()
    print(f"\nИтог: {PASS} ok, {FAIL} fail")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())