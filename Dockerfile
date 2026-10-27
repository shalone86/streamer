FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DISPLAY=:99 \
    PULSE_SERVER=unix:/tmp/pulse/native

# Virtual screen, window manager, sound, encoder, remote-control tools, VNC for logging in.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg \
        xvfb openbox x11vnc novnc websockify xdotool \
        pulseaudio ffmpeg \
        python3 python3-websocket \
        supervisor \
        fonts-liberation fonts-noto-core fonts-noto-color-emoji \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

COPY rootfs/ /
COPY server/ /app/server/
COPY roku/ /app/roku/

RUN chmod +x /usr/local/bin/*.sh

# 8080: control server (setup page, Roku API, video stream). 6080: browser view for logging in.
EXPOSE 8080 6080
VOLUME /config

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
