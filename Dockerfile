# Backend only: no GPIO, SPI devices or privileged container required.
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN pip install --no-cache-dir Pillow==12.3.0 tzdata==2026.5 \
    && groupadd --gid 10001 hvv \
    && useradd --uid 10001 --gid 10001 --create-home hvv
COPY hvv_display /app/hvv_display
USER hvv
EXPOSE 8080
ENV HVV_CONFIG=/data/config.json \
    HVV_CREDENTIALS_FILE=/data/credentials.env \
    HVV_STATION_CACHE=/data/stations.json \
    HVV_WEB_ENV_FILE=/data/web.env \
    HVV_WEB_HOST=0.0.0.0 \
    HVV_WEB_TLS_CERTFILE=/data/tls.crt \
    HVV_WEB_TLS_KEYFILE=/data/tls.key
CMD ["python", "-m", "hvv_display.web"]
