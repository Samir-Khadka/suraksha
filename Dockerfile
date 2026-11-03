# syntax=docker/dockerfile:1
# Suraksha — production image (FastAPI + Leaflet frontend, one process).
# Pinned base for reproducible builds; multi-stage to keep runtime lean.
ARG PYTHON_TAG=3.12.16-slim-bookworm

FROM python:${PYTHON_TAG} AS builder
ENV PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --prefix=/install -r requirements.txt

FROM python:${PYTHON_TAG} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=builder /install /usr/local
RUN useradd -m -u 10001 suraksha
WORKDIR /app
COPY --chown=suraksha:suraksha app.py ./
COPY --chown=suraksha:suraksha static/ ./static/
USER suraksha
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
