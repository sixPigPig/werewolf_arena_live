ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS dependencies

ARG PNPM_VERSION=10.32.1
RUN npm install --global "pnpm@${PNPM_VERSION}"
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/admin-web/package.json apps/admin-web/package.json
COPY apps/mobile-web/package.json apps/mobile-web/package.json
COPY apps/web/package.json apps/web/package.json
COPY packages/game-client/package.json packages/game-client/package.json
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter admin-web...

FROM dependencies AS development
ENV VITE_API_PROXY_TARGET=http://api:8000 \
    VITE_ADMIN_AUTH_ENABLED=true \
    VITE_ADMIN_DEV_LOGIN_ENABLED=true \
    VITE_ADMIN_PREVIEW_MODE=false
COPY apps/admin-web apps/admin-web
EXPOSE 8080
CMD ["pnpm", "--dir", "apps/admin-web", "dev", "--host", "0.0.0.0", "--port", "8080"]

FROM dependencies AS builder
ARG VITE_API_BASE_URL=""
ARG ADMIN_LOGIN_REQUIRED=true
ARG ADMIN_DEVELOPMENT_LOGIN=false
ARG ADMIN_FIXTURE_PREVIEW=false
COPY apps/admin-web apps/admin-web
RUN VITE_API_BASE_URL="${VITE_API_BASE_URL}" \
    VITE_ADMIN_AUTH_ENABLED="${ADMIN_LOGIN_REQUIRED}" \
    VITE_ADMIN_DEV_LOGIN_ENABLED="${ADMIN_DEVELOPMENT_LOGIN}" \
    VITE_ADMIN_PREVIEW_MODE="${ADMIN_FIXTURE_PREVIEW}" \
    pnpm --dir apps/admin-web build

FROM ${NGINX_IMAGE} AS runtime

ENV API_UPSTREAM=http://api:8000 \
    NGINX_ENVSUBST_FILTER=^API_UPSTREAM$

COPY apps/admin-web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /workspace/apps/admin-web/dist /usr/share/nginx/html
RUN touch /run/nginx.pid \
    && chown nginx:nginx /run/nginx.pid \
    && chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]
