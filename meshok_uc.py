# -*- coding: utf-8 -*-
"""Сборщик Мешка через undetected-chromedriver с ПОСТОЯННЫМ профилем.

Логика (Cloudflare кэштся по профилю браузера):
1. Используем фиксированный профиль data/chrome_meshok_profile — один раз
   проходишь капчу вручную, профиль «запоминает» cf_clearance.
2. Повторные запуски открываются без капчи (даже в headless), т.к. профиль тот же.
3. Собирает карточки (актуальные селекторы подхватываются по маркерам),
   скроллит для догрузки, сохраняет cookies + сырой HTML для разбора.

Запуск:  python meshok_uc.py "микросхемы" [--headless] [--limit 50] [--dump]
"""
import sys, io, time, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from pathlib import Path
import argparse

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

BASE = Path(r"C:\Users\skrob\OneDrive\Рабочий стол\Gold_Parser")
PROFILE = BASE / "data" / "chrome_meshok_profile"


def parse_price(t):
    t = (t or "").replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    t = t.replace("₽", "").replace("руб.", "").replace("Бесплатно", "0")
    t = t.replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", t)
    return float(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="микросхемы")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--dump", action="store_true", help="сохранить HTML для разбора")
    args = ap.parse_args()

    q = re.sub(r"\s+", "+", args.query)
    url = f"https://meshok.net/search?searchString={q}"

    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1500,950")
    PROFILE.mkdir(parents=True, exist_ok=True)

    driver = uc.Chrome(options=opts, user_data_dir=str(PROFILE),
                       headless=args.headless, version_main=None)
    try:
        print("Открываю:", url, f"(headless={args.headless})", flush=True)
        driver.get(url)
        # если капча — ждём ручного клика до 3 мин
        t0 = time.time()
        blocks = []
        cf_detected = False
        while time.time() - t0 < 180:
            html = driver.page_source
            soup = BeautifulSoup(html, "html.parser")
            low = html.lower()
            # актуальные карточки ищем по разнообразным маркерам
            blocks = (soup.find_all("div", class_=lambda c: c and "itemCardList" in c)
                      or soup.find_all("div", class_=lambda c: c and ("item" in c and "price" in (c or "")))
                      or soup.find_all("a", href=re.compile(r"/item/\d+")))
            cf_detected = any(m in low for m in
                              ["just a moment", "cf_chl", "cloudflare", "вы не робот", "подтвердите"])
            if blocks and not cf_detected:
                print("Карточки получены.", flush=True)
                break
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(2)
        if not blocks:
            print("Карточек нет (капча не пройдена или вёрстка сменилась).", flush=True)

        # сохраняем cookies
        try:
            ck = [{"name": c["name"], "value": c["value"], "domain": c.get("domain", "")}
                  for c in driver.get_cookies()]
            (BASE / "data").mkdir(exist_ok=True)
            (BASE / "data" / "cookies_meshok.json").write_text(json.dumps(ck), encoding="utf-8")
            has_cf = any(c["name"] == "cf_clearance" for c in ck)
            print(f"cookies: {len(ck)} шт, cf_clearance={'есть' if has_cf else 'нет'}", flush=True)
        except Exception as e:
            print("cookies fail:", e, flush=True)

        if args.dump:
            (BASE / "data" / "meshok_dump.html").write_text(html, encoding="utf-8", errors="replace")
            print("HTML сохранён: data/meshok_dump.html", flush=True)

        # разбор карточек (актуальная вёрстка Мешка: Nuxt-компоненты itemCard_*)
        soup = BeautifulSoup(html, "html.parser")
        seen = set()
        cards = soup.select("div[class*='itemCard']")
        count = 0
        for b in cards:
            a = b.select_one("a[class*='wrapper']") or b.find("a")
            link = a.get("href") if a and a.get("href") else ""
            if "/item/" not in link:
                continue
            if link.startswith("/"):
                link = "https://meshok.net" + link
            if link in seen:
                continue
            seen.add(link)
            title_el = b.select_one("div[class*='itemTitle']")
            title = title_el.get_text(" ", strip=True) if title_el else (
                title_el.attrs.get("title", "") if title_el and title_el.attrs.get("title") else "?")
            price_el = b.select_one("div[class*='price']")
            price = parse_price(price_el.get_text(" ", strip=True)) if price_el else None
            print(f"  {price if price is not None else '?':>9} | {str(title)[:50]} | {link[:70]}", flush=True)
            count += 1
            if count >= args.limit:
                break
        print(f"Всего карточек: {count} (уникальных ссылок)", flush=True)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()