FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY src/ src/
COPY tests/ tests/
COPY input/ input/

ENTRYPOINT ["python", "-m"]
