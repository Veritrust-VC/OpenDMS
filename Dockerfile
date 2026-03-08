FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS deps
COPY pyproject.toml .
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
RUN pip install --no-cache-dir ".[dev]"
COPY src/ ./src/
COPY tests/ ./tests/
RUN mkdir -p /data/documents
CMD ["uvicorn", "opendms.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
