FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY src/ src/
COPY tests/ tests/
COPY input/ input/

# Non-root runtime user, UID 1000 by default. docker-compose.pipeline.yml
# overrides this uniformly via PIPELINE_UID/PIPELINE_GID when set (needed on
# native Linux hosts whose user isn't UID 1000 - see README, "Non-root
# containers"). A per-command `docker compose run --user` flag is not a
# substitute: it only overrides the one service named on the command line,
# not the depends_on services Compose starts alongside it - confirmed
# directly. Every file each stage writes is mode 0600 (owner-only), so all
# three services must run as the same UID or a later stage gets Permission
# denied reading an earlier one's output - also confirmed directly.
RUN useradd --create-home --no-log-init --uid 1000 --shell /usr/sbin/nologin appuser
USER appuser

ENTRYPOINT ["python", "-m"]
