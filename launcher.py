# -*- coding: utf-8 -*-
"""Лаунчер Gold Parser: локальный веб-сервер с красивой панелью.

Запускает python-команды бота по кнопкам и возвращает вывод в интерфейс.
Двойной клик по run.bat запускает этот сервер и открывает браузер.

Команды — белый список: запускаем только известные (prices, uc, shops, monitor).
"""
import sys
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
PORT = 8756

ALLOWED = {"prices", "uc", "shops", "monitor", "boards", "scan", "hunt"}
# множества аргументов допускаем для uc (site, query)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html", "/launcher.html"):
            self._send(200, "text/html; charset=utf-8",
                       (BASE / "launcher.html").read_bytes())
        elif self.path == "/good":
            # список выгодных ссылок из data/good_links.json
            try:
                links = json.loads((BASE / "data" / "good_links.json").read_text("utf-8"))
            except Exception:
                links = []
            self._send(200, "application/json", json.dumps(links).encode())
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path != "/run":
            self._send(404, "text/plain", b"not found")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            args = body.get("args") or []
        except Exception:
            self._send(400, "application/json", json.dumps({"error": "bad request"}).encode())
            return
        if not args or args[0] not in ALLOWED:
            self._send(403, "application/json",
                       json.dumps({"error": f"команда не разрешена: {args[:1]}"}).encode())
            return
        # ограничение аргументов: только сайты и запросы без хитростей
        safe = [a for a in args if isinstance(a, str)
                and len(a) < 200 and "\n" not in a and ";" not in a and "&&" not in a]
        try:
            p = subprocess.run([sys.executable, "app.py"] + safe,
                               cwd=str(BASE), capture_output=True, timeout=600,
                               encoding="utf-8", errors="replace")
            out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
            self._send(200, "application/json",
                       json.dumps({"output": out[-6000:]}).encode())
        except subprocess.TimeoutExpired:
            self._send(200, "application/json",
                       json.dumps({"output": "Таймаут (команда выполняется долго — см. окно)."}).encode())
        except Exception as e:
            self._send(500, "application/json", json.dumps({"error": str(e)}).encode())


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Gold Parser panel: http://127.0.0.1:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("остановлено")


if __name__ == "__main__":
    main()