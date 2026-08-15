FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system fitops && adduser --system --ingroup fitops fitops

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY --chown=fitops:fitops backend/ /app/

USER fitops

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
