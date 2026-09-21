# A runner image with dependencies fully baked in at build time, per
# `docs/ARCHITECTURE.md`'s "Dependency installation/build is a separate,
# visible step" — `docker build` has ordinary internet access, but the
# runtime container joins a network-disabled sandbox, so nothing at
# migration-run time may need to install or download anything.
#
# The venv lives outside `/workspace` on purpose: `DockerRunner` bind-mounts
# a freshly staged copy of the repository over `/workspace` at runtime,
# which would otherwise shadow (hide) anything baked in there at build time.
FROM python:3.12-slim
RUN pip install --no-cache-dir uv
WORKDIR /build
COPY pyproject.toml uv.lock ./
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv sync --frozen --no-dev
