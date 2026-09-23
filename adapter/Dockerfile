FROM phpdockerio/php:8.4-fpm
RUN apt-get update && apt-get install -y --no-install-recommends php8.4-gd php8.4-redis php8.4-mysql php8.4-gmp php8.4-bcmath mariadb-server redis-server python3 python3-venv && rm -rf /var/lib/apt/lists/*
WORKDIR /application
COPY upstream/ ./
ENV COMPOSER_ALLOW_SUPERUSER=1
RUN composer install --no-interaction --no-progress --no-dev
COPY adapter/ /adapter/
RUN python3 -m venv /opt/adapter && /opt/adapter/bin/pip install aiohttp==3.12.15 pydantic==2.11.9
RUN mkdir -p /run/mysqld && chown -R root:root /var/lib/mysql /run/mysqld
ENTRYPOINT ["/bin/sh", "/adapter/start.sh"]
