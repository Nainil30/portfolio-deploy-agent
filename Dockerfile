FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PDA_HOME=/app PDA_DB=/app/data/pda.db
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
RUN useradd --create-home bot && mkdir -p /app/data && chown -R bot /app/data
USER bot

VOLUME ["/app/data"]
CMD ["pda", "bot"]
