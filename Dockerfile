# Gold Parser — Docker (экспериментально; основная платформа — Windows локально)
# Для продакшен-запуска на Linux/VPS нужно адаптировать пути (BASE) и Chrome.

FROM python:3.12-slim

WORKDIR /app

# системные зависимости для Chrome/undetected-chromedriver
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg unzip fonts-liberation libnss3 libnspr4 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libasound2 libpangocairo-1.0-0 \
    ca-certificates && rm -rf /var/lib/apt/lists/*

# ставим google-chrome-stable
RUN wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get update && apt-get install -y /tmp/chrome.deb && rm /tmp/chrome.deb

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Здесь обязательно: заменить BASE на /app в конфиге при переносе на Linux!
ENV PYTHONUNBUFFERED=1

# entrypoint задаётся в docker-compose (bot или worker)
CMD ["python", "app.py", "prices"]