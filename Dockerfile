# Python version matches the project's Python 3.11 runtime.
# Bookworm avoids the stale Bullseye package URLs shown in the failed build log.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Compiler tools are required if a dependency (for example TgCrypto) needs a source build.
# Python headers are already included with the official python image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install -r requirements.txt

COPY . .

# The Heroku process is a worker, not a web dyno. bot.py starts its own aiohttp endpoint.
CMD ["python", "-u", "bot.py"]
