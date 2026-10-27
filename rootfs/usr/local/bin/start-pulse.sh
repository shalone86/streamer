#!/bin/bash
# A virtual sound card: Chrome plays into the "stream" sink, ffmpeg records its monitor.
rm -f /tmp/pulse/native
exec pulseaudio -n --daemonize=no --exit-idle-time=-1 --disallow-exit \
    --use-pid-file=no --system=no -F /etc/pulse/streamer.pa
