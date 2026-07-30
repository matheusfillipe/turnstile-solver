FROM python:3.12-slim

# Stock Google Chrome, not Chromium: Cloudflare treats the patched/rebuilt browsers
# as automation and serves an interactive challenge that never clears.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg xvfb \
        fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
        libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libx11-xcb1 \
        libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
        http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY solver.py service.py ./

ENV PORT=8191 \
    MAX_WORKERS=2 \
    TS_PROFILE_DIR=/profiles/ts_profile

EXPOSE 8191
CMD ["python", "service.py"]
