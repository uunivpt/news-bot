FROM node:22-bookworm-slim AS reel-deps
WORKDIR /build
COPY reel/package.json ./reel/package.json
RUN npm install --prefix reel --omit=dev --no-audit --no-fund

FROM python:3.12-slim
WORKDIR /app
COPY --from=reel-deps /usr/local/ /usr/local/
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=reel-deps /build/reel/node_modules /app/reel/node_modules
COPY . .
CMD ["python", "run.py", "--interval", "300"]
