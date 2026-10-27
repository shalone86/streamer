#!/bin/bash
# The browser view (port 6080) for logging in. Set VNC_PASSWORD to require a password.
if [ -n "$VNC_PASSWORD" ]; then
    auth=(-passwd "$VNC_PASSWORD")
else
    auth=(-nopw)
fi
exec x11vnc -display :99 -forever -shared -localhost -rfbport 5900 -quiet "${auth[@]}"
