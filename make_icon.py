# -*- coding: utf-8 -*-
"""Генерация иконки-ярлыка 'Gold Parser' и запуск.

Создаёт gold_icon.ico в папке проекта и .lnk на рабочем столе (реальном и OneDrive,
если есть), запускающий бота (меню) через pythonw (без чёрного окна).
Тихий запуск меню в окне — но меню нужно консоль, поэтому используем консольное
окно (cmd /k run.bat), чтобы был виден ввод/вывод.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ICO_PATH = BASE / "gold_icon.ico"

def make_icon():
    from PIL import Image, ImageDraw
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = []
    for s in sizes:
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # корпус микросхемы
        pad = int(s * 0.08)
        body = (pad, int(s * 0.3), s - pad, int(s * 0.75))
        d.rounded_rectangle(body, radius=int(s * 0.06), fill=(212, 175, 55, 255),
                            outline=(255, 217, 102, 255), width=max(1, s // 32))
        # вырезы-«ножки»
        n = 8
        w = max(1, int(s * 0.03))
        for i in range(n):
            x = int(s * (0.14 + 0.72 * i / (n - 1)))
            d.line([(x, int(s * 0.18)), (x, int(s * 0.30))], fill=(255, 217, 102, 255), width=w)
            d.line([(x, int(s * 0.75)), (x, int(s * 0.87))], fill=(255, 217, 102, 255), width=w)
        # точка-«ключ» угла
        d.ellipse([int(s * 0.18), int(s * 0.38), int(s * 0.24), int(s * 0.44)],
                  fill=(90, 60, 0, 255))
        imgs.append(img)
    imgs[-1].save(ICO_PATH, sizes=[(s, s) for s in sizes], append_images=imgs[:-1])
    return ICO_PATH

def make_shortcut(name, target_args, icon_path):
    import subprocess
    ps = (
        "$ws = New-Object -ComObject WScript.Shell;"
        f"$s = $ws.CreateShortcut('{name}.lnk');"
        f"$s.TargetPath = '{target_args[0]}';"
        f"$s.Arguments = '{target_args[1]}';"
        f"$s.WorkingDirectory = '{BASE}';"
        f"$s.IconLocation = '{icon_path},0';"
        "$s.Save()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr

def main():
    icon = make_icon()
    print("иконка:", icon)
    targets = []
    # рабочий стол OneDrive
    od = Path(os.environ.get("OneDrive")) / "Рабочий стол" if os.environ.get("OneDrive") else None
    real = Path.home() / "Desktop"
    for d in {d for d in (od, real, BASE) if d and d.exists()}:
        lnk = d / "Gold Parser"
        ok, err = make_shortcut(lnk, (sys.executable, "-m app.py"), icon)
        # Запускать через cmd, чтобы окно консоли сохранялось + каталог проекта
        ok, err = make_shortcut(lnk, (r"C:\Windows\System32\cmd.exe",
                                      f"/k cd /d \"{BASE}\" && python app.py"), icon)
        print(("OK  " if ok else "FAIL"), lnk, err.strip()[:120] if err else "")

if __name__ == "__main__":
    import os
    main()