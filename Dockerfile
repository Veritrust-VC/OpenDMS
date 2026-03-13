FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y poppler-utils pandoc && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY pyproject.toml .
COPY README.md .
COPY src/ ./src/
RUN pip install --no-cache-dir .

FROM base AS production
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY src/ ./src/
RUN mkdir -p /data/documents
EXPOSE 8002
CMD ["uvicorn", "opendms.main:app", "--host", "0.0.0.0", "--port", "8002"]

FROM base AS development
COPY pyproject.toml .
COPY README.md .
COPY src/ ./src/
RUN pip install --no-cache-dir ".[dev]"
RUN mkdir -p /data/documents
CMD ["uvicorn", "opendms.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
