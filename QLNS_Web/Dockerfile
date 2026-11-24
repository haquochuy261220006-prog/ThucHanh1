FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    DB_DRIVER="ODBC Driver 18 for SQL Server" \
    DB_WINDOWS_AUTH=false \
    DB_ENCRYPT=yes \
    DB_TRUST_SERVER_CERTIFICATE=no

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg tesseract-ocr tesseract-ocr-vie tesseract-ocr-eng unixodbc \
    && curl -fsSLo /tmp/packages-microsoft-prod.deb https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && ACCEPT_EULA=Y apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -f /tmp/packages-microsoft-prod.deb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-azure.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-azure.txt

COPY . .
RUN useradd --system --create-home appuser
USER appuser

EXPOSE 8000
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--timeout=600", "app:app"]
