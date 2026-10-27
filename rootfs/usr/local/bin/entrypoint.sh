#!/bin/bash
# Runs everything as the user Unraid expects (nobody:users = 99:100 by default).
set -e

PUID=${PUID:-99}
PGID=${PGID:-100}

if ! getent group "$PGID" >/dev/null; then
    groupadd -g "$PGID" streamer
fi
if ! getent passwd streamer >/dev/null; then
    useradd -u "$PUID" -g "$PGID" -o -d /config -s /bin/bash streamer
fi

mkdir -p /config /tmp/pulse /tmp/hls /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
chown "$PUID:$PGID" /config /tmp/pulse /tmp/hls

exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
