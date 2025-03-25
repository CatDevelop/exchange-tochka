FROM python:3.12.3-slim

ENV PYTHONUNBUFFERED 1


RUN apt-get update \
    && apt-get install -y curl build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --no-root

COPY . .

EXPOSE 8000

RUN chmod +x /app/scripts/start_with_migration.sh /app/scripts/start.sh

ENTRYPOINT ["./scripts/start_with_migration.sh"]
