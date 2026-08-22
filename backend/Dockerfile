FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg (with libass/libx264/drawtext) + fonts for captions
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fontconfig curl \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend/pyproject.toml backend/requirements.lock.txt ./
RUN pip install -r requirements.lock.txt
COPY backend/app ./app
COPY backend/tests ./tests
RUN pip install -e ".[dev]"

# runtime dirs (mounted via compose in practice)
RUN mkdir -p /app/storage /app/assets /app/configs
COPY configs /app/configs
COPY fonts /app/fonts

ENV STORAGE_DIR=/app/storage \
    ASSETS_DIR=/app/assets \
    CONFIGS_DIR=/app/configs

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
