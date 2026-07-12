ARG NODE_IMAGE=node:22-alpine
ARG NGINX_IMAGE=nginx:1.27-alpine

FROM ${NODE_IMAGE} AS dependencies

ARG PNPM_VERSION=10.32.1
RUN npm install --global "pnpm@${PNPM_VERSION}"
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/mobile-web/package.json apps/mobile-web/package.json
COPY packages/game-client/package.json packages/game-client/package.json
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter mobile-web...

FROM dependencies AS development
ENV VITE_API_PROXY_TARGET=http://api:8000
COPY apps/mobile-web apps/mobile-web
COPY packages/game-client packages/game-client
EXPOSE 8080
CMD ["pnpm", "--dir", "apps/mobile-web", "dev", "--host", "0.0.0.0", "--port", "8080"]

FROM dependencies AS builder
ARG VITE_API_BASE_URL=""
COPY apps/mobile-web apps/mobile-web
COPY packages/game-client packages/game-client
COPY scripts/check-mobile-bundle.mjs scripts/check-mobile-bundle.mjs
RUN VITE_API_BASE_URL="${VITE_API_BASE_URL}" pnpm --dir apps/mobile-web build

FROM ${NGINX_IMAGE} AS runtime

ENV API_UPSTREAM=http://api:8000 \
    NGINX_ENVSUBST_FILTER=^API_UPSTREAM$

COPY apps/mobile-web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /workspace/apps/mobile-web/dist /usr/share/nginx/html
RUN touch /run/nginx.pid \
    && chown nginx:nginx /run/nginx.pid \
    && chown -R nginx:nginx /etc/nginx/conf.d /var/cache/nginx
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD ["wget", "-q", "--spider", "http://127.0.0.1:8080/healthz"]
