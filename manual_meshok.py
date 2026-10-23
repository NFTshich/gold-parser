# -*- coding: utf-8 -*-
"""Сбор Мешка через uc с ручной разблокировкой Cloudflare капчи.

Шаги:
1. Открывает ВИДИМОЕ окно Chrome (uc, не headless).
2. Если Cloudflare просит «нажмите что вы не робот» — ждёт, пока пользователь
   кликнет в окне вручную (до wait_manual_click секунд).
3. Когда страница загрузилась реально (есть карточки или нет Cloudflare) —
   собирает лоты и сохраняет cookies в data/cookies_meshok.json.
4. Печатает найденные лоты.

Запуск:  python manual_meshok.py "микросхемы"  [--limit N]
"""
import sys, io, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
from pathlib import Path

import undetected_chromedriver as uc
from bs4 import BeautifulSoup

BASE = Path(r"C:\Users\skrob\OneDrive\Рабочий стол\Gold_Parser")


def parse_price(t):
    t = (t or "").replace("\xa0", "").replace(" ", "").replace("₽", "").replace("руб.", "")
    t = t.replace("Благотворительныйлот", "").replace("Бесплатно", "0").replace(",", ".")
    try:
        return float(t)
    except Exception:
        return None


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "микросхемы"
    import re
    q = re.sub(r"\s+", "+", query)
    url = f"https://meshok.net/search?searchString={q}"
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--log-level=3")
    opts.add_argument("--window-size=1500,950")
    # НЕ headless — чтобы можно было кликнуть капчу вручную
    driver = uc.Chrome(options=opts)
    try:
        print("Открываю (видимое окно):", url, flush=True)
        driver.get(url)
        # ждём, пока капча/Cloudflare уйдёт ИЛИ появятся блоки карточек
        cf_marker = ["cloudflare", "cf_chl", "checkpoint", "no-captcha", "капча",
                     "continue - robot", "Confirm you", "подтвердите"]
        t0 = time.time()
        timeout = int(sys.argv[sys.argv.index("--limit") + 1]) * 60 if "--limit" in sys.argv else 180
        timeout = 180  # по умолчанию до 3 минут на ручной клик
        print(f"Если Мешок показал капчу «вы не робот» — кликни её вручную. Жду до {timeout//60} мин...", flush=True)
        blocks = []
        while time.time() - t0 < timeout:
            try:
                html = driver.page_source
                soup = BeautifulSoup(html, "html.parser")
                blocks = soup.find_all("div", class_=lambda c: c and "itemCardList" in c)
                low = html.lower()
                cf = any(m in low for m in ["cloudflare", "cf_chl", "checkpoint", "подтвердите, что вы не робот", "вы не робот"])
            except Exception:
                blocks, cf = [], True
            if blocks:
                print("Карточки появились — Cloudflare пройден/обойдён.", flush=True)
                break
            # скроллим, чтобы спровоцировать догрузку
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(2)
        if not blocks:
            print("Не дождался карточек (или капча не пройтена). Проверь окно браузера.", flush=True)
            # всё равно сохраним cookies, вдруг помогут позже
        # сохраняем cookies → data/cookies_meshok.json
        cookies = []
        try:
            for c in driver.get_cookies():
                cookies.append({"name": c["name"], "value": c["value"], "domain": c.get("domain", "")})
        except Exception as e:
            print("не удалось взять cookies:", e, flush=True)
        try:
            (BASE / "data").mkdir(exist_ok=True)
            (BASE / "data" / "cookies_meshok.json").write_text(json.dumps(cookies), encoding="utf-8")
            print(f"Сохранено cookies Мешка: {len(cookies)} шт -> data/cookies_meshok.json", flush=True)
        except Exception as e:
            print("не сохранил cookies:", e, flush=True)

        # печатаем карточки
        seen = set()
        for b in blocks:
            a = b.find("a")
            link = ("https://meshok.net" + a.get("href")) if a and a.get("href") else ""
            if link in seen:
                continue
            seen.add(link)
            title = b.find("div", class_=lambda c: c and "itemTitle" in c)
            price = b.find("div", class_=lambda c: c and "priceAndIcons" in c)
            name = title.get_text(" ", strip=True) if title else "?"
            pv = parse_price(price.get_text(" ", strip=True)) if price else None
            print(f"  {pv if pv is not None else '?'} | {name[:45]} | {link[:60]}", flush=True)
        print(f"\nВсего карточек: {len(seen)}", flush=True)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()