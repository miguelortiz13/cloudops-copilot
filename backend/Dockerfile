# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /srv

# Librerias del sistema que necesita mssql-python (driver de Azure SQL); el
# driver ODBC viene dentro del paquete.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libltdl7 libkrb5-3 libgssapi-krb5-2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY pipelines ./pipelines
COPY migrations ./migrations
COPY alembic.ini .

# Usuario sin privilegios: el API solo lee de Azure y escribe en DATA_DIR.
RUN useradd --create-home --uid 10001 copilot \
    && mkdir -p /data && chown copilot:copilot /data
USER copilot

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/openapi.json')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
