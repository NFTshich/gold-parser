@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem Если передан флаг --menu — открываем консольное меню
if /i "%~1"=="--menu" (
    python app.py
    goto :eof
)

rem Иначе — красивая веб-панель: стартуем сервер и открываем браузер
start "GoldParser server" /min python launcher.py
timeout /t 1 >nul
start "" "http://127.0.0.1:8756/"
exit