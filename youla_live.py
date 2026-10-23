# -*- coding: utf-8 -*-
"""Юла — сбор карточек через ЖИВЫЕ элементы (driver.find_elements), не page_source.

Юла рендерит карточки через Vue (виртуальный скролл); page_source не содержит
полные href. Берём элементы из живого DOM: ищем a со ссылкой на лот и рядом
название/цену.
"""
import sys, io, time, json, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import undetected_chromedriver as uc
from bs4 import BeautifulSoup

BASE = Path(r"C:\Users\skrob\OneDrive\Рабочий стол\Gold_Parser")
PROFILE = BASE / "data" / "chrome_youla_profile"
QUERY = sys.argv[1] if len(sys.argv) > 1 else "микросхемы"


def main():
    PROFILE.mkdir(parents=True, exist_ok=True)
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    driver = uc.Chrome(options=opts, user_data_dir=str(PROFILE), headless=False)
    try:
        driver.get("https://youla.ru")
        time.sleep(4)
        # ввод запроса
        box = None
        for sel in ["input[placeholder*='Поиск']", "input[type='search']", "input[name='q']", "form input"]:
            try:
                box = driver.find_element(By.CSS_SELECTOR, sel)
                break
            except Exception:
                continue
        if box:
            box.clear()
            box.send_keys(QUERY)
            box.send_keys(Keys.ENTER)
            print("ввёл запрос + Enter", flush=True)
        # ждём карточки: получаем ссылки на лоты через JS (один проход, без stale)
        t0 = time.time()
        lot_links = []
        while time.time() - t0 < 90:
            links = driver.execute_script(
                "return Array.from(document.querySelectorAll('a')).map(a=>a.href)")
            lot_links = []
            for h in links or []:
                if "youla.ru/" in h and not any(x in h for x in
                        ["mail.ru", "ok.ru", "vk.ru", "vkplay", "help.youla",
                         "promo", "/login", "/moskva", "/product/create",
                         "news.mail", "love.mail", "cloud.mail", "tariffs",
                         "youla.ru/cities", "youla.ru/msk"]):
                    lot_links.append(h)
            if lot_links:
                print(f"найдено ссылок на лоты: {len(lot_links)}", flush=True)
                break
            time.sleep(3)
        if not lot_links:
            print("не нашёл ссылок на лоты", flush=True)

        # выводим
        seen = set()
        n = 0
        for h in lot_links:
            if h in seen:
                continue
            seen.add(h)
            print(f"  ? | ? | {h[:75]}", flush=True)
            n += 1
            if n >= 15:
                break
        # сохраним cookies и html
        try:
            ck = [{"name": c["name"], "value": c["value"]} for c in driver.get_cookies()]
            (BASE / "data" / "cookies_youla.json").write_text(json.dumps(ck), encoding="utf-8")
            if lot_links:
                (BASE / "data" / "youla_lots.json").write_text(
                    json.dumps([{"title": "?", "price": "?", "url": h} for h in lot_links[:50]],
                               ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print("сохранение:", e, flush=True)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()