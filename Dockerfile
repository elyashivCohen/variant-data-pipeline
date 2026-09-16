FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY src/ src/
COPY tests/ tests/
COPY input/ input/

# Non-root runtime user, fixed UID 1000. All pipeline stages share this same
# image and the same UID, and outputs live in a Docker-managed named volume
# (docker-compose.yml), not a host bind mount - so there is no host UID to
# match, only container-to-container consistency, which a single fixed UID
# already guarantees. The one exception is the `init` service in
# docker-compose.yml, which overrides `user: root` for one thing only: fixing
# up the named volume's ownership on first use (Docker creates a new volume's
# mount point root-owned when nothing in the image already owns that path).
RUN useradd --create-home --no-log-init --uid 1000 --shell /usr/sbin/nologin appuser
USER appuser

ENTRYPOINT ["python", "-m"]
