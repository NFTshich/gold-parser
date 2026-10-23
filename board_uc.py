# -*- coding: utf-8 -*-
"""РЈРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ uc-СЃР±РѕСЂС‰РёРє Р±Р°СЂР°С…РѕР»РѕРє (РњРµС€РѕРє/Р®Р»Р°/РђРІРёС‚Рѕ) СЃ РїРѕСЃС‚РѕСЏРЅРЅС‹Рј РїСЂРѕС„РёР»РµРј.

РРґРµСЏ (РїСЂРѕРІРµСЂРµРЅРѕ РЅР° РњРµС€РєРµ): РѕС‚РєСЂС‹РІР°РµРј РїР»РѕС‰Р°РґРєСѓ С‡РµСЂРµР· undetected-chromedriver РІ
РџРћРЎРўРћРЇРќРќРћРњ РїСЂРѕС„РёР»Рµ; РїРµСЂРІС‹Р№ Р·Р°РїСѓСЃРє вЂ” РІСЂСѓС‡РЅСѓСЋ РїСЂРѕС…РѕРґРёРј РєР°РїС‡Сѓ ('СЏ РЅРµ СЂРѕР±РѕС‚'),
РїСЂРѕС„РёР»СЊ Р·Р°РїРѕРјРёРЅР°РµС‚ cf_clearance/session; СЃР»РµРґСѓСЋС‰РёРµ Р·Р°РїСѓСЃРєРё вЂ”
Р±РµР· РєР°РїС‡Рё (РґР°Р¶Рµ --headless).  РљР°СЂС‚РѕС‡РєРё Р»РѕС‚РѕРІ РїР°СЂСЃРёРј РїРѕ Р°РєС‚СѓР°Р»СЊРЅРѕР№ РІС‘СЂСЃС‚РєРµ.

РџСЂРѕС„РёР»Рё:   data/chrome_<site>_profile
cookies:   data/cookies_<site>.json
РґР°РјРї:      data/<site>_dump.html (РїСЂРё --dump)

Запуск:
  python board_uc.py meshok "микросхемы с золотом" [--headless] [--limit 20]
  python board_uc.py youla  "микросхемы" [--headless] [--limit 20]
  python board_uc.py avito  "микросхемы" [--headless] [--limit 20]
"""
import sys, io, time, json, re, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from pathlib import Path
import argparse

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

BASE = Path(r"C:\Users\skrob\OneDrive\Р Р°Р±РѕС‡РёР№ СЃС‚РѕР»\Gold_Parser")

# РћСЃРЅРѕРІРЅР°СЏ РІРµСЂСЃРёСЏ СѓСЃС‚Р°РЅРѕРІР»РµРЅРЅРѕРіРѕ Chrome (РІР°Р¶РЅРѕ РґР»СЏ СЃРѕРІРїР°РґРµРЅРёСЏ СЃ ChromeDriver).
# uc РїСЂРё СЂР°СЃСЃРѕРіР»Р°СЃРѕРІР°РЅРёРё (РґСЂР°Р№РІРµСЂ РґСЂСѓРіРѕРіРѕ РјР°Р¶РѕСЂР°) РЅРµ СЃС‚Р°СЂС‚СѓРµС‚.
CHROME_MAIN = 154


def _load_cookies(site):
    """Читает сохранённые cookies площадки (data/cookies_<site>.json) -> list[dict]."""
    p = BASE / "data" / f"cookies_{site}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _apply_cookies(driver, site):
    """Подставляет сохранённые cookies в открытый контекст uc (для обхода капчи)."""
    cks = _load_cookies(site)
    if not cks:
        return
    for c in cks:
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain") or ""
        if not name or value is None:
            continue
        try:
            driver.add_cookie({"name": name, "value": value, "domain": domain})
        except Exception:
            pass


def _build_driver(profile, headless=False):
    """Создаёт uc.Chrome с постоянным профилем, прокси и стандартными опциями.

    Прокси берётся из config.load_uc_proxy() (data/proxy.txt или UC_PROXY).
    """
    import config as _cfg
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1500,950")
    proxy = _cfg.load_uc_proxy()
    if proxy:
        opts.add_argument(f"--proxy-server={proxy}")
    profile = Path(profile)
    profile.mkdir(parents=True, exist_ok=True)
    return uc.Chrome(options=opts, user_data_dir=str(profile),
                     headless=headless, version_main=CHROME_MAIN)

# РєРѕРЅС„РёРі РїР»РѕС‰Р°РґРѕРє: URL РїРѕРёСЃРєР°, СЃРµР»РµРєС‚РѕСЂС‹ РєР°СЂС‚РѕС‡РµРє (РіРёР±РєРѕ РїРѕ РјР°СЂРєРµСЂР°Рј)
SITES = {
    "meshok": {
        "url": lambda q: f"https://meshok.net/listing?search={q}",
        "link_prefix": "https://meshok.net",
        "has_real_domain": True,
        # РєР°СЂС‚РѕС‡РєР° СЃ Р»РѕС‚РѕРј: Р»СЋР±РѕР№ Р±Р»РѕРє, РІРЅСѓС‚СЂРё a[href*=item/], div[class*=price], div[class*=itemTitle]
    },
    "youla": {
        "url": lambda q: f"https://youla.ru/moskva?q={q}",
        "link_prefix": "",
        "has_real_domain": True,
    },
    "avito": {
        "url": lambda q: f"https://www.avito.ru/all?q={q}",
        "link_prefix": "",
        "has_real_domain": True,
    },
}

# РјР°СЂРєРµСЂС‹ РєР°РїС‡Рё/Р±Р»РѕРєРёСЂРѕРІРєРё
CF_MARKERS = ("just a moment", "cf_chl", "cloudflare", "вы не робот",
              "подтвердите", "captcha", "before you continue", "act as a robot",
              "доступ к сайту ограничен", "проверка безопасности",
              "turnstile", "challenge-platform", "cf-turnstile", "hcaptcha",
              "recaptcha", "мы заметили подозрительную активность")


def _dedup(lots):
    seen = set()
    out = []
    for l in lots:
        u = l.get("url")
        if u and u in seen:
            continue
        if u:
            seen.add(u)
        out.append(l)
    return out


# Юла: отсеиваем мусорные ссылки (города/категории/help). Настоящий лот — URL
# с несколькими сегментами пути, содержащий транслит названия + id или слаг.
import urllib.parse as _up

_SINGLE_SEG = {"help", "moskva", "yaroslavl", "sankt-peterburg", "ekaterinburg",
               "novosibirsk", "krasnodar", "krasnoyarsk", "chelyabinsk", "tyumen",
               "rostov-na-donu", "voronezh", "samara", "ufa", "omsk", "perm",
               "volgograd", "ekb", "msk", "spb", "cities", "login", "product"}


def _is_youla_lot(url: str) -> bool:
    """True, если ссылка похожа на лот Юлы (не город/территория/служебная)."""
    if "youla.ru" not in url:
        return False
    # отбрасываем служебные и внешние
    for bad in ("mail.ru", "ok.ru", "vk.ru", "vkplay", "help.youla", "/login",
                "/product/create", "/user/", "/promo", "/cities"):
        if bad in url:
            return False
    try:
        path = _up.urlparse(url).path.strip("/").split("/")
    except Exception:
        return False
    if not path:
        return False
    first = path[0].lower()
    # односегментный путь вида youla.ru/<город> — не лот
    if len(path) == 1 and first in _SINGLE_SEG:
        return False
    # путь без подкатегории/имени лота (только город+категория) — не лот
    # лот: минимум 2-3 сегмента и последний содержит id или слаг товара
    return len(path) >= 2


def parse_price(t):
    ss = (t or "").replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    for w in ("₽", "руб.", "руб", "RUB", "Бесплатно", "БЕСПЛАТНО"):
        ss = ss.replace(w, "")
    ss = ss.replace("ценообразование", "").replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", ss)
    return float(m.group(0)) if m else (0.0 if ("бесплат" in (t or "").lower()) else None)


def human_delay(lo=2.5, hi=6.0):
    """Пауза, чтобы не выглядеть ботом (случайные задержки между действиями)."""
    time.sleep(random.uniform(lo, hi))


def solve_captcha(driver):
    """Точка входа для сервиса решения капчи (2captcha/CapSolver).

    Сейчас — заглушка: если задан CAPTCHA_API_KEY, здесь позже будет вызов API.
    Возвращает True, если капча решена автоматически (используется в циклах ожидания).
    """
    import config as _cfg
    if not _cfg.CAPTCHA_API_KEY:
        return False
    # TODO: вставить вызов 2captcha/capsolver по captcha_id из страницы.
    return False


def warm_up(driver, site):
    """Прогрев профиля перед поиском: главная -> подождать -> проскроллить.

    Уменьшает вероятность упереться в капчу на первом же поиске.
    """
    try:
        cfg = SITES.get(site or "")
        host = {"meshok": "https://meshok.net/", "avito": "https://www.avito.ru/",
                "youla": "https://youla.ru/moskva"}.get(site or "", "https://meshok.net/")
        driver.get(host)
        time.sleep(random.uniform(3.0, 5.0))
        for _ in range(random.randint(1, 2)):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(random.uniform(1.0, 1.8))
    except Exception:
        pass


def extract_lots(soup, site_key):
    """Р“РёР±РєРѕ РґРѕСЃС‚Р°С‘С‚ РєР°СЂС‚РѕС‡РєРё: РёС‰РµРј СЃСЃС‹Р»РєРё РЅР° /item/ (РјРµС€РѕРє), РёРЅР°С‡Рµ РјР°СЂРєРµСЂС‹."""
    lots = []

    if site_key == "meshok":
        seen = set()
        cards = soup.select("a[class*='itemCard']") or soup.select("div[class*='itemCard']")
        for b in cards:
            a = b if b.name == "a" else (b.select_one("a[class*='wrapper']") or b.find("a"))
            href = a.get("href", "") if a else ""
            if "/item/" not in href:
                continue
            link = ("https://meshok.net" + href) if href.startswith("/") else href
            if link in seen:
                continue
            seen.add(link)
            title_el = b.select_one("[class*='itemTitle'], [class*='titleBlock'], [class*='title']")
            title = title_el.get_text(" ", strip=True) if title_el else "?"
            price_el = b.select_one("[class*='price']")
            price = parse_price(price_el.get_text(" ", strip=True)) if price_el else None
            lots.append({"title": title, "price": price, "url": link})
        return lots

    # Р®Р»Р° / РђРІРёС‚Рѕ: РёС‰РµРј СЃСЃС‹Р»РєРё РїРѕ РґР°РЅРЅС‹Рј РјР°СЂРєРµСЂР°Рј (Р·Р°РїРѕР»РЅСЏРµРј СЃРµР»РµРєС‚РѕСЂС‹ РїРѕСЃР»Рµ С‚РµСЃС‚Р°)
    # --- РђРІРёС‚Рѕ: РєР°СЂС‚РѕС‡РєРё data-marker="item*" ---
    if site_key == "avito":
        # РєР°СЂС‚РѕС‡РєРё РђРІРёС‚Рѕ: <div data-marker="item"> СЃ item-title / item-price
        for card in soup.select('[data-marker="item"]'):
            a = card.select_one('a[data-marker="item-title"]') or card.select_one("a[href*=avito.ru]")
            title_el = card.select_one('[data-marker="item-title"]')
            pv_el = card.select_one('[data-marker="item-price-value"]') or card.select_one('[itemprop="price"]')
            price = None
            if pv_el is not None:
                if pv_el.name == "meta":
                    price = parse_price(pv_el.get("content"))
                else:
                    price = parse_price(pv_el.get_text(" ", strip=True))
            title = title_el.get_text(" ", strip=True) if title_el else (a.get_text(" ", strip=True) if a else "?")
            href = a.get("href", "") if a else ""
            if href and href.startswith("/"):
                href = "https://www.avito.ru" + href
            if not href:
                continue
            lots.append({"title": title, "price": price, "url": href})
        return lots

    # Р®Р»Р°
    if site_key == "youla":
        for a in soup.select('a[href*="youla.ru/"], a.product_item, a[class*="product_item"], a[data-testid*="product"]'):
            href = a.get("href", "")
            if not href or "youla.ru/" not in href:
                continue
            title_el = a.select_one("h3, [class*='title'], span[class*='title']") or a
            title = title_el.get_text(" ", strip=True)
            price_el = a.select_one("[class*='price'], span[class*='price']")
            price = parse_price(price_el.get_text(" ", strip=True)) if price_el else None
            lots.append({"title": title, "price": price, "url": href})
        return lots

    return lots


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=list(SITES))
    ap.add_argument("query", nargs="?", default="микросхемы")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args()

    site = args.site
    cfg = SITES[site]
    q = re.sub(r"\s+", "+", args.query)
    url = cfg["url"](q)
    profile = BASE / "data" / f"chrome_{site}_profile"
    profile.mkdir(parents=True, exist_ok=True)

    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1500,950")

    driver = _build_driver(profile, args.headless if 'args' in dir() else False)
    try:
        print(f"[{site}] РѕС‚РєСЂС‹РІР°СЋ: {url} (headless={args.headless})", flush=True)
        print(f"  Р•СЃР»Рё РєР°РїС‡Р° 'СЏ РЅРµ СЂРѕР±РѕС‚' вЂ” РєР»РёРєРЅРё РµС‘ РІ РѕРєРЅРµ. Р–РґСѓ РґРѕ 3 РјРёРЅ.", flush=True)
        driver.get(url)

        # Р®Р»Р°: СЂРµР·СѓР»СЊС‚Р°С‚С‹ РїРѕРґРіСЂСѓР¶Р°СЋС‚СЃСЏ С‚РѕР»СЊРєРѕ РїРѕСЃР»Рµ РІРІРѕРґР° Р·Р°РїСЂРѕСЃР° РІ РїРѕР»Рµ + Enter
        if site == "youla":
            try:
                import time as _t
                _t.sleep(3)
                # РїСЂРѕР±СѓРµРј РЅРµСЃРєРѕР»СЊРєРѕ СЃРµР»РµРєС‚РѕСЂРѕРІ РїРѕРёСЃРєРѕРІРѕР№ СЃС‚СЂРѕРєРё
                for sel in ["input[type='search']", "input[placeholder*='РџРѕРёСЃРє']",
                            "input[placeholder*='С‚РѕРІР°СЂ']", "input[data-testid*='search']",
                            "input[name='q']", "form input"]:
                    try:
                        box = driver.find_element("css selector", sel)
                        box.clear()
                        box.send_keys(args.query)
                        box.send_keys("\ue007")  # Enter
                        print(f"  [youla] РІРІС‘Р» Р·Р°РїСЂРѕСЃ РІ РїРѕР»Рµ ({sel}) + Enter", flush=True)
                        break
                    except Exception:
                        continue
            except Exception as e:
                print(f"  [youla] РІРІРѕРґ РїРѕРёСЃРєР° РЅРµ СѓРґР°Р»СЃСЏ: {e}", flush=True)

        t0 = time.time()
        html = ""
        lots = []
        # РґР»СЏ Р®Р»С‹ Р¶РґС‘Рј РїРѕСЏРІР»РµРЅРёСЏ СЃРµС‚РєРё С‚РѕРІР°СЂРѕРІ (РѕРЅРё РіСЂСѓР·СЏС‚СЃСЏ Р»РµРЅРёРІРѕ)
        waited_youla = False
        while time.time() - t0 < 220:
            html = driver.page_source
            low = html.lower()
            soup = BeautifulSoup(html, "html.parser")
            # avito: РєР°СЂС‚РѕС‡РєРё РµСЃС‚СЊ РІ page_source (data-marker="item") -> BS4
            # youla: РІРёСЂС‚СѓР°Р»СЊРЅС‹Р№ СЂРµРЅРґРµСЂ -> С‚РѕР»СЊРєРѕ JS РЅРёР¶Рµ
            lots = extract_lots(soup, site) if site != "youla" else []

            # РђРІРёС‚Рѕ: РєР°СЂС‚РѕС‡РєРё СЂРµРЅРґРµСЂСЏС‚СЃСЏ JS -> СЃСЃС‹Р»РєРё Рё РЅР°Р·РІР°РЅРёСЏ/С†РµРЅС‹ С‡РµСЂРµР· Р¶РёРІС‹Рµ СЌР»РµРјРµРЅС‚С‹
            if site == "avito" and not lots:
                if not waited_youla:
                    print("  [avito] Р¶РґСѓ РѕС‚СЂРёСЃРѕРІРєСѓ РІС‹РґР°С‡Рё + JS-СЃР±РѕСЂ...", flush=True)
                    waited_youla = True
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    cards = driver.execute_script(
                        "return Array.from(document.querySelectorAll('[data-marker=\"item\"]')).map(el=>{"
                        " const a=el.querySelector('a[href*=avito.ru]')||el.querySelector('a')||{};"
                        " const h3=el.querySelector('h3')||{};"
                        " const p=el.querySelector('[data-marker*=price],[itemprop=price],[class*=price]')||{};"
                        " return {href:a.href||'', title:(h3.innerText||'').trim(),"
                        " price:(p.innerText||p.getAttribute('content')||'').trim()}; }).filter(o=>o.href)") or []
                except Exception as exc:
                    print("  [avito] JS-РѕС€РёР±РєР°:", exc, flush=True)
                    cards = []
                for o in cards:
                    lots.append({"title": o.get("title", ""), "price": parse_price(o.get("price", "")),
                                 "url": o.get("href", "")})
                lots = _dedup(lots)
                if lots:
                    print(f"  РќР°Р№РґРµРЅРѕ РѕР±СЉСЏРІР»РµРЅРёР№ (JS): {len(lots)}", flush=True)
                    break
                time.sleep(3)
                continue

            # Р®Р»Р°: РєР°СЂС‚РѕС‡РєРё РіСЂСѓР·СЏС‚СЃСЏ С‡РµСЂРµР· Vue -> СЃРѕР±РёСЂР°РµРј СЃСЃС‹Р»РєРё С‡РµСЂРµР· JS
            if site == "youla" and not lots:
                if not waited_youla:
                    print("  [youla] Р¶РґСѓ РѕС‚СЂРёСЃРѕРІРєСѓ СЃРµС‚РєРё С‚РѕРІР°СЂРѕРІ + JS-СЃР±РѕСЂ...", flush=True)
                    waited_youla = True
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    links = driver.execute_script(
                        "return Array.from(document.querySelectorAll('a')).map(a=>a.href).filter("
                        "h=>h.includes('youla.ru/') && !h.includes('mail.ru') && !h.includes('ok.ru') "
                        "&& !h.includes('vk.ru') && !h.includes('vkplay') && !h.includes('/login') "
                        "&& !h.includes('/product/create') && !h.includes('/user/') && !h.includes('/promo') "
                        "&& !h.includes('/cities') && !h.includes('/moskva') && !h.includes('/yaroslavl') "
                        "&& !(/\/[a-z]{3,10}$/.test(new URL(h).pathname.split('/').filter(Boolean)[0]))"
                        " || h.indexOf('/platy-rasshirieniia')>0 || h.indexOf('na-zapchasti')>0)") or []
                except Exception:
                    links = []
                for l in links:
                    lots.append({"title": "?", "price": None, "url": l})
                lots = _dedup(lots)
                if lots:
                    print(f"  РќР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє (JS): {len(lots)}", flush=True)
                    break
                time.sleep(3)
                continue

            # РµСЃР»Рё РєР°СЂС‚РѕС‡РµРє РЅРµС‚ Рё СЌС‚Рѕ РЅРµ РєР°РїС‡Р° вЂ” СЃРєСЂРѕР»Р»РёРј
            if not lots and not any(m in low for m in CF_MARKERS):
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                except Exception:
                    pass
            if lots:
                print(f"  РќР°Р№РґРµРЅРѕ РєР°СЂС‚РѕС‡РµРє: {len(lots)} вЂ” Cloudflare/РєР°РїС‡Р° РїСЂРѕР№РґРµРЅР°.", flush=True)
                break
            time.sleep(2)

        # СЃРѕС…СЂР°РЅСЏРµРј cookies
        try:
            ck = [{"name": c["name"], "value": c["value"], "domain": c.get("domain", "")}
                  for c in driver.get_cookies()]
            (BASE / "data").mkdir(exist_ok=True)
            (BASE / "data" / f"cookies_{site}.json").write_text(json.dumps(ck), encoding="utf-8")
            print(f"  cookies: {len(ck)} С€С‚ -> data/cookies_{site}.json", flush=True)
        except Exception as e:
            print("  cookies fail:", e, flush=True)

        if args.dump:
            (BASE / "data" / f"{site}_dump.html").write_text(html, encoding="utf-8", errors="replace")
            print(f"  HTML СЃРѕС…СЂР°РЅС‘РЅ: data/{site}_dump.html", flush=True)

        if not lots:
            print("  РљР°СЂС‚РѕС‡РµРє РЅРµ РїРѕР»СѓС‡РµРЅРѕ (РєР°РїС‡Р° РЅРµ РїСЂРѕР№РґРµРЅР° РёР»Рё РІС‘СЂСЃС‚РєР° СЃРјРµРЅРёР»Р°СЃСЊ).", flush=True)
            print("  Р”Р°РјРї СЃРѕС…СЂР°РЅС‘РЅ вЂ” РјРѕР¶РЅРѕ СЂР°Р·РѕР±СЂР°С‚СЊ Р°РєС‚СѓР°Р»СЊРЅС‹Рµ СЃРµР»РµРєС‚РѕСЂС‹.", flush=True)
            return

        # РїРµС‡Р°С‚СЊ
        seen = set()
        count = 0
        for l in lots:
            u = l["url"]
            if u and u in seen:
                continue
            if u:
                seen.add(u)
            price = l["price"]
            print(f"  {price if price is not None else '?':>9} | {str(l['title'])[:50]} | {u[:65]}", flush=True)
            count += 1
            if count >= args.limit:
                break
        print(f"[{site}] Р’СЃРµРіРѕ: {count}", flush=True)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def collect_lots(site: str, query: str, limit: int = 200,
                 dump: bool = False, max_pages: int | str = 8,
                 _profile_idx: int = 0) -> list[dict]:
    """Открывает площадку через uc, собирает лоты [{title, price, url}].

    При капче — ждёт ручного клика в открытом окне (один раз).
    Для avito ходим по страницам (?p=2,3..), для мешка/юлы — прокрутка.
    max_pages: число страниц, или 'all' (очень много — про все страницы).
    _profile_idx: номер профиля при ротации (0 = основной, 1 = _2, 2 = _3).
                 При капче на действующем профиле переключаемся на следующий.
    """
    cfg = SITES[site]
    q = re.sub(r"\s+", "+", query)
    prof_name = f"chrome_{site}_profile" if _profile_idx == 0 else f"chrome_{site}_profile_{_profile_idx + 1}"
    profile = BASE / "data" / prof_name
    profile.mkdir(parents=True, exist_ok=True)
    driver = _build_driver(profile, headless=False)
    try:
        _apply_cookies(driver, site)  # переиспользуем сохранённые cookies (Блок: стабильность)
        warm_up(driver, site)  # прогреем профиль перед поиском (чуть реже капча)
        lots: list[dict] = []
        seen_urls: set[str] = set()
        first = True
        # avito: СЃС‚СЂР°РЅРёС†С‹ 1..max_pages ('all' -> РґРѕ 500); РІ others вЂ” РѕРґРЅР° РІС‹РґР°С‡Р° СЃРѕ СЃРєСЂРѕР»Р»РѕРј
        if site == "avito":
            n = 500 if max_pages in ("all", "РІСЃРµ", "*") else max(1, int(max_pages))
            pages = list(range(1, n + 1))
        else:
            pages = [0]

        for idx, page_no in enumerate(pages, 1):
            if idx > 1:
                human_delay()  # пауза между страницами, чтобы не быть ботом
            if site == "avito":
                url = cfg["url"](q)
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}p={page_no}"
            else:
                url = cfg["url"](q)
            total_pages = len(pages)
            if first:
                print(f"[{site}] РѕС‚РєСЂС‹РІР°СЋ: {url} (СЃС‚СЂР°РЅРёС†Р° {page_no or 1} РёР· {total_pages})", flush=True)
                print("  Р•СЃР»Рё РєР°РїС‡Р° 'СЏ РЅРµ СЂРѕР±РѕС‚' вЂ” РєР»РёРєРЅРё РµС‘ РІ РѕРєРЅРµ (РґРѕ 3 РјРёРЅ).", flush=True)
                first = False
            else:
                print(f"[{site}] СЃС‚СЂР°РЅРёС†Р° {page_no} РёР· {total_pages} вЂ” СЃРѕР±СЂР°РЅРѕ {len(lots)} Р»РѕС‚РѕРІ", flush=True)
            driver.get(url)
            if site == "youla":
                import time as _t
                _t.sleep(2)
                for sel in ["input[type='search']", "input[placeholder*='РџРѕРёСЃРє']",
                            "input[placeholder*='С‚РѕРІР°СЂ']", "input[name='q']", "form input"]:
                    try:
                        box = driver.find_element("css selector", sel)
                        box.clear()
                        box.send_keys(query)
                        box.send_keys("\ue007")
                        print("  [youla] РІРІС‘Р» Р·Р°РїСЂРѕСЃ + Enter", flush=True)
                        break
                    except Exception:
                        continue
            # Р¶РґС‘Рј РєР°СЂС‚РѕС‡РєРё РЅР° СЌС‚РѕР№ СЃС‚СЂР°РЅРёС†Рµ + РґРѕРіСЂСѓР·РєР° СЃРєСЂРѕР»Р»РѕРј (РІРёСЂС‚СѓР°Р»СЊРЅС‹Р№ СЂРµРЅРґРµСЂ)
            t0 = time.time()
            page_lots: list[dict] = []
            scrolls = 0
            while time.time() - t0 < 90:
                html = driver.page_source
                soup = BeautifulSoup(html, "html.parser")
                page_lots = extract_lots(soup, site) if site != "youla" else []
                if site == "youla" and not page_lots:
                    gq = _try_youla_graphql(driver, query)
                    if gq:
                        page_lots = gq
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        links = driver.execute_script(
                            "return Array.from(document.querySelectorAll('a')).map(a=>a.href).filter("
                            "h=>h.includes('youla.ru/') && !h.includes('mail.ru') && !h.includes('ok.ru') "
                            "&& !h.includes('vk.ru') && !h.includes('vkplay') && !h.includes('/login') "
                            "&& !h.includes('/product/create') && !h.includes('/user/') && !h.includes('/promo') "
                            "&& !h.includes('/cities') && !h.includes('/moskva') && !h.includes('/yaroslavl')"
                            ")") or []
                    except Exception:
                        links = []
                    for l in (links or []):
                            if _is_youla_lot(l):
                                page_lots.append({"title": "?", "price": None, "url": l})
                    page_lots = _dedup(page_lots)
                # РїРѕСЃР»Рµ РїРѕСЏРІР»РµРЅРёСЏ РєР°СЂС‚РѕС‡РµРє вЂ” РґРѕРєСЂСѓС‡РёРІР°РµРј РІРЅРёР·, С‡С‚РѕР±С‹ РІРёСЂС‚СѓР°Р»СЊРЅС‹Р№
                # СЂРµРЅРґРµСЂ РґРѕРіСЂСѓР·РёР» РѕСЃС‚Р°Р»СЊРЅС‹Рµ СЃРѕ СЃС‚СЂР°РЅРёС†С‹
                if site == "youla" and page_lots and scrolls < 4:
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        scrolls += 1
                        time.sleep(1.5)
                        soup2 = BeautifulSoup(driver.page_source, "html.parser")
                        page_lots = extract_lots(soup2, site) if site != "youla" else page_lots
                        # СЃРЅРѕРІР° СЃРѕР±РёСЂР°РµРј СЃСЃС‹Р»РєРё Р®Р»С‹ (РґРѕРіСЂСѓР¶РµРЅРЅС‹Рµ) Рё СЃР»РёРІР°РµРј
                        if site == "youla":
                            try:
                                links = driver.execute_script(
                                    "return Array.from(document.querySelectorAll('a')).map(a=>a.href).filter("
                                    "h=>h.includes('youla.ru/') && !h.includes('mail.ru') && !h.includes('ok.ru') "
                                    "&& !h.includes('vk.ru') && !h.includes('vkplay') && !h.includes('/login') "
                                    "&& !h.includes('/product/create') && !h.includes('/user/') && !h.includes('/promo') "
                                    "&& !h.includes('/cities') && !h.includes('/moskva') && !h.includes('/yaroslavl')"
                                    ")") or []
                                page_lots += [{"title": "?", "price": None, "url": l} for l in (links or []) if _is_youla_lot(l)]
                            except Exception:
                                pass
                        page_lots = _dedup(page_lots)
                        continue
                    except Exception:
                        pass
                if page_lots:
                    break
                time.sleep(2)
            # РґРµРґСѓРї РїРѕ url Рё РґРѕР±Р°РІР»СЏРµРј
            for it in page_lots:
                u = it.get("url") or ""
                if not u or u in seen_urls:
                    continue
                seen_urls.add(u)
                lots.append(it)
            if dump and html:
                (BASE / "data" / f"{site}_dump.html").write_text(
                    html, encoding="utf-8", errors="replace")
            # обрываем по лимиту ТОЛЬКО для мешка/юлы (они скролл-выдачи);
            # для avito проходим все страницы, лимит срезается в конце
            if site != "avito" and len(lots) >= limit:
                break
        # если ничего не собрано И похоже на капчу — пробуем следующий профиль
        if not lots and _profile_idx < 2:
            try:
                low_all = driver.page_source.lower()
                looks_captcha = any(m in low_all for m in CF_MARKERS)
            except Exception:
                looks_captcha = False
            if looks_captcha:
                print(f"  [rot] капча на профиле {_profile_idx + 1} — пробую следующий...", flush=True)
                try:
                    driver.quit()
                except Exception:
                    pass
                return collect_lots(site, query, limit=limit, dump=dump,
                                    max_pages=max_pages, _profile_idx=_profile_idx + 1)
        return lots[:limit]
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def collect_many(site: str, queries: list[str], limit_per: int = 30,
                 max_pages: int | str = 8) -> list[dict]:
    """Прогоняет МНОЖЕСТВО запросов по одной площадке, держа ОДИН браузер/профиль.

    Эффективно для hunt: открыли профиль один раз, гоняем все ключи, меняя URL.
    Returns list[{title, price, url}] (без дедупликации между запросами — дубли
    срежутся позднее фильтром по url в отчёте).
    """
    if site == "avito":
        return _collect_many_avito(queries, limit_per, max_pages)
    return _collect_many_scroll(queries, limit_per, max_pages, site)


def _try_youla_graphql(driver, query, city="moskva"):
    """Пытается получить лоты Юлы через GraphQL fetch() из контекста браузера.

    Возвращает список dict {title, price, url} или [] (если эндпоинт не отдал данные
    без авторизации). Безопасно: просто пробуем запросы, при ошибке возвращаем [].
    """
    endpoints = [f"https://api.youla.ru/graphql", f"https://youla.ru/api/graphql"]
    q = query.replace('"', '\\"')
    for ep in endpoints:
        js = f"""async () => {{
          try {{
            const r = await fetch("{ep}", {{
              method: "POST", headers: {{"Content-Type": "application/json"}},
              body: JSON.stringify({{ query: '{{ search(query:"{q}", citySlug:"{city}") {{ products {{ id title price {{ amount }} }}}} }}' }})
            }});
            const j = await r.json();
            return JSON.stringify(j);
          }} catch(e) {{ return "ERR:" + e.message; }}
        }}"""
        try:
            res = driver.execute_script("return (%s)()" % js)
        except Exception:
            continue
        if not res or res.startswith("ERR:"):
            continue
        import json as _j
        try:
            d = _j.loads(res)
        except Exception:
            continue
        # пробуем найти товары в разных местах ответа
        products = None
        for key in ("products", "search"):
            if key in d:
                products = d[key]
                break
        if isinstance(products, dict):
            products = products.get("products") or products.get("items") or []
        if isinstance(products, list) and products:
            lots = []
            for p in products:
                if isinstance(p, dict):
                    pid = p.get("id")
                    title = (p.get("title") or "").strip()
                    amt = (p.get("price") or {}).get("amount") if isinstance(p.get("price"), dict) else None
                    lots.append({"title": title, "price": (amt / 100.0) if amt else None,
                                 "url": f"https://youla.ru/{city}/-{pid}" if pid else ""})
            return [l for l in lots if l.get("url")]
    return []


def _collect_many_avito(queries: list[str], limit_per: int,
                        max_pages: int | str) -> list[dict]:
    """Авито в hunt: каждый ключ — обход страниц ?p=2,3.. (без скролла подвала)."""
    profile = BASE / "data" / "chrome_avito_profile"
    driver = _build_driver(profile, headless=False)
    n_pages = 500 if max_pages in ("all", "все", "*") else max(1, int(max_pages))
    try:
        _apply_cookies(driver, "avito")
        warm_up(driver, "avito")
        all_lots: list[dict] = []
        for qi, query in enumerate(queries, 1):
            q = re.sub(r"\s+", "+", query)
            base_url = f"https://www.avito.ru/all?q={q}"
            print(f"  [avito] ключ {qi}/{len(queries)}: «{query}»", flush=True)
            if qi == 1:
                print("  Если капча — кликни её в окне (пикуется один раз).", flush=True)
            page_collected = 0
            for p in range(1, n_pages + 1):
                url = f"{base_url}&p={p}"
                driver.get(url)
                # ждём появления карточек на этой странице (без скролла вниз)
                page_lots: list[dict] = []
                t0 = time.time()
                while time.time() - t0 < 25:
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    page_lots = extract_lots(soup, "avito")
                    if page_lots:
                        break
                    time.sleep(2)
                if page_lots:
                    print(f"    стр. {p}: +{len(page_lots)}", flush=True)
                    for it in page_lots:
                        if page_collected >= limit_per:
                            break
                        all_lots.append(it)
                        page_collected += 1
                else:
                    print(f"    стр. {p}: пусто, стоп страниц", flush=True)
                    break
                if page_collected >= limit_per:
                    break
        return all_lots
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _collect_many_scroll(queries: list[str], limit_per: int,
                         max_pages: int | str, site: str) -> list[dict]:
    cfg = SITES[site]
    cfg = SITES[site]
    profile = BASE / "data" / f"chrome_{site}_profile"
    profile.mkdir(parents=True, exist_ok=True)
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1500,950")
    driver = _build_driver(profile, headless=False)
    try:
        all_lots: list[dict] = []
        for qi, query in enumerate(queries, 1):
            q = re.sub(r"\s+", "+", query)
            url = cfg["url"](q)
            if site == "avito":
                url = f"{url}&p=1"
            print(f"  [{site}] РєР»СЋС‡ {qi}/{len(queries)}: В«{query}В» ({url[:70]})", flush=True)
            if qi == 1:
                print("  Р•СЃР»Рё РєР°РїС‡Р° вЂ” РєР»РёРєРЅРё РµС‘ РІ РѕРєРЅРµ (РїРёРєСѓРµС‚СЃСЏ РѕРґРёРЅ СЂР°Р·).", flush=True)
            driver.get(url)
            if site == "youla":
                import time as _t
                _t.sleep(2)
                for sel in ["input[type='search']", "input[placeholder*='РџРѕРёСЃРє']",
                            "input[placeholder*='С‚РѕРІР°СЂ']", "input[name='q']", "form input"]:
                    try:
                        box = driver.find_element("css selector", sel)
                        box.clear()
                        box.send_keys(query)
                        box.send_keys("\ue007")
                        break
                    except Exception:
                        continue
            # Р¶РґС‘Рј РєР°СЂС‚РѕС‡РєРё РїРѕ СЌС‚РѕРјСѓ РєР»СЋС‡Сѓ (СЃ РґРѕРіСЂСѓР·РєРѕР№)
            t0 = time.time()
            page_lots: list[dict] = []
            scrolls = 0
            while time.time() - t0 < 90:
                soup = BeautifulSoup(driver.page_source, "html.parser")
                page_lots = extract_lots(soup, site) if site != "youla" else []
                if site == "youla" and not page_lots:
                    gq = _try_youla_graphql(driver, query)
                    if gq:
                        page_lots = gq
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        links = driver.execute_script(
                            "return Array.from(document.querySelectorAll('a')).map(a=>a.href).filter("
                            "h=>h.includes('youla.ru/') && !h.includes('mail.ru') && !h.includes('ok.ru') "
                            "&& !h.includes('vk.ru') && !h.includes('vkplay') && !h.includes('/login') "
                            "&& !h.includes('/product/create') && !h.includes('/user/') && !h.includes('/promo') "
                            "&& !h.includes('/cities') && !h.includes('/moskva') && !h.includes('/yaroslavl')"
                            ")") or []
                    except Exception:
                        links = []
                    for l in (links or []):
                            if _is_youla_lot(l):
                                page_lots.append({"title": "?", "price": None, "url": l})
                    page_lots = _dedup(page_lots)
                if site == 'youla' and page_lots and scrolls < 4:
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                        scrolls += 1
                        time.sleep(1.5)
                        soup2 = BeautifulSoup(driver.page_source, "html.parser")
                        page_lots = extract_lots(soup2, site) if site != "youla" else page_lots
                        page_lots = _dedup(page_lots)
                        continue
                    except Exception:
                        pass
                if page_lots:
                    break
                time.sleep(2)
            print(f"    СЃРѕР±СЂР°РЅРѕ: {len(page_lots)}", flush=True)
            all_lots.extend(page_lots[:limit_per])
        return all_lots
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()

