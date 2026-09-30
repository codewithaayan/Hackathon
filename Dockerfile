FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && addgroup --system urbanpulse \
    && adduser --system --ingroup urbanpulse --home /nonexistent urbanpulse

COPY --chown=urbanpulse:urbanpulse backend ./backend

USER urbanpulse
EXPOSE 8000

CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --limit-concurrency 40 --no-proxy-headers"]
