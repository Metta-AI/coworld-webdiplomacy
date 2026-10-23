FROM node:22-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.11.8 AS uv
FROM phpdockerio/php:8.4-fpm
# CVE-2026-109618 and CVE-2026-109619 (unauthenticated RCE) are fixed in PHP 8.4.27.
# The tag floats, so a stale cached base would otherwise build a vulnerable image.
RUN php -r 'exit(version_compare(PHP_VERSION, "8.4.27", "<") ? 1 : 0);' || { echo "PHP $(php -r 'echo PHP_VERSION;') is older than 8.4.27; rebuild with --pull" >&2; exit 1; }
RUN apt-get update && apt-get install -y --no-install-recommends php8.4-gd php8.4-redis php8.4-mysql php8.4-gmp php8.4-bcmath mariadb-server redis-server nginx python3 python3-venv && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/ /usr/local/
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /application
COPY webdiplomacy/ ./
ENV COMPOSER_ALLOW_SUPERUSER=1
RUN composer install --no-interaction --no-progress --no-dev && cd sse-server && npm ci --omit=dev
RUN cd game-src && npm ci && PUBLIC_URL=. npm run build && rm -rf node_modules /root/.npm
WORKDIR /opt
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-cache
COPY adapter/ /opt/adapter/
COPY players/ /opt/players/
COPY php/ /opt/php/
COPY config/ /opt/config/
RUN mkdir -p /run/mysqld /run/webdip/logs && chown -R root:root /var/lib/mysql /run/mysqld && \
    /opt/.venv/bin/python -m adapter.boot --bake && \
    rm -rf /run/webdip /application/config.php /application/sse-server/.env
STOPSIGNAL SIGTERM
EXPOSE 8080
ENTRYPOINT ["/opt/.venv/bin/python", "-m", "adapter.boot"]
