ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS builder

ARG UV_VERSION=0.11.27
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /workspace/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

FROM ${PYTHON_IMAGE} AS runtime

ENV PATH="/workspace/apps/api/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system --gid 10001 werewolf \
    && useradd --system --uid 10001 --gid werewolf --home-dir /workspace --create-home werewolf

WORKDIR /workspace/apps/api
COPY --from=builder --chown=werewolf:werewolf /workspace/apps/api/.venv .venv
COPY --chown=werewolf:werewolf apps/api/app app
COPY --chown=werewolf:werewolf apps/api/alembic alembic
COPY --chown=werewolf:werewolf apps/api/alembic.ini apps/api/pyproject.toml ./
# Keep the repository-relative fallback used by legacy judge voice assets.
COPY --chown=werewolf:werewolf apps/web/public/judge-voice /workspace/apps/web/public/judge-voice

RUN mkdir -p logs && chown werewolf:werewolf logs
USER werewolf

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2)"]

CMD ["python", "-m", "app.cli", "serve", "--host", "0.0.0.0", "--port", "8000"]
