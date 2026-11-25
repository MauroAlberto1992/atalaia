# Mini-COP backend: FastAPI + aisstream ingestion.
FROM python:3.12-slim

# No .pyc files on disk, logs straight to stdout (docker logs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so this layer is cached when only code changes.
COPY pyproject.toml ./
COPY src ./src
COPY config ./config
# Editable install on purpose: the code finds config/ relative to its source
# folder (minicop/config.py -> /app/config). A regular install would move the
# code into site-packages and lose that path.
# Then create an unprivileged user to run as: if the service is compromised,
# the attacker doesn't get root inside the container. USER takes the numeric
# id so tools (and Kubernetes' runAsNonRoot) can verify it without /etc/passwd.
RUN pip install --no-cache-dir -e . \
    && useradd --create-home --uid 10001 minicop
USER 10001

EXPOSE 8000

# Docker marks the container healthy once /health answers. The stdlib is used
# so the image needs no curl.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]

CMD ["uvicorn", "minicop.api:app", "--host", "0.0.0.0", "--port", "8000"]
