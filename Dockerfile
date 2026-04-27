# ============================================================
# USN_COMPLETE — production image
# ~450 MB (base 130 + LibreOffice-core ~200 + deps ~100 + fonts ~20)
# LibreOffice нужен для конвертации Excel-шаблонов деклараций в PDF
# ============================================================
FROM python:3.12-slim AS base

# System fonts + LibreOffice core для xlsx→pdf конвертации.
# libreoffice-core + libreoffice-calc — минимум для soffice --convert-to pdf
# Liberation Sans совместим с Arial (основной шрифт ФНС-форм).
# DejaVu — универсальный запас.
# Основной шрифт Tahoma для штампов — уже в репо: modules/edo_stamps/fonts/
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation \
        fonts-dejavu-core \
        libreoffice-core \
        libreoffice-calc \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Deps слой (кэшируется, пока requirements.txt не меняется)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Application layer
COPY . .

# Non-root
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=8000

EXPOSE 8000

# Railway пробрасывает $PORT — используем shell form чтобы переменная подставилась
CMD exec uvicorn api.main:app --host $HOST --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips='*'
