#!/bin/sh
set -eu
cd /application
if [ -n "${COGAME_LOAD_REPLAY_URI:-}" ]; then
    exec /opt/adapter/bin/python /adapter/server.py
fi
mkdir -p /run/mysqld cache
chown mysql:mysql /run/mysqld
mariadbd --user=mysql --bind-address=127.0.0.1 --innodb-buffer-pool-size=128M > /tmp/mariadb.log 2>&1 &
redis-server --bind 127.0.0.1 --daemonize yes
until mariadb-admin ping --silent; do sleep 1; done
mariadb -e "CREATE DATABASE webdiplomacy; CREATE USER 'webdiplomacy'@'localhost' IDENTIFIED BY 'mypassword123'; GRANT ALL ON webdiplomacy.* TO 'webdiplomacy'@'localhost';"
mariadb webdiplomacy < install/FullInstall/fullInstall.sql
mariadb webdiplomacy < install/createBotAccounts.sql
# Ordinary members participate in draw voting; upstream Bot accounts cannot vote.
mariadb webdiplomacy -e "UPDATE wD_Users SET type='User' WHERE username REGEXP '^bot[1-7]$';"
cp config.sample.php config.php
sed -i "s/'webdiplomacy-db'/'127.0.0.1'/g; s/'redis'/'127.0.0.1'/g" config.php
find variants -name variant.php -exec sh -c 'mkdir -p "$(dirname "$1")/cache"' sh {} \;
php /adapter/engine.php create > /tmp/episode.json
php -S 127.0.0.1:8090 -t /application > /tmp/php.log 2>&1 &
exec /opt/adapter/bin/python "/adapter/${WEBDIP_MODE:-server}.py"
