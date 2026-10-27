#!/bin/bash
# Chrome with the ad blocker (installed by policy) and a profile kept in /config,
# so logins survive restarts.
PROFILE=/config/chrome
mkdir -p "$PROFILE"

# A container restart changes the hostname; Chrome would then refuse the profile as
# "in use on another computer".
rm -f "$PROFILE"/Singleton*

# Chrome is always stopped abruptly here; don't offer to "restore pages" on the TV.
PREFS="$PROFILE/Default/Preferences"
if [ -f "$PREFS" ]; then
    sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[A-Za-z]*"/"exit_type":"Normal"/' "$PREFS"
fi

sandbox=()
if [ "$CHROME_NO_SANDBOX" = "1" ]; then
    sandbox=(--no-sandbox)
fi
# Extra flags, e.g. CHROME_FLAGS="--proxy-server=http://192.168.1.2:3128".
read -r -a extra <<< "$CHROME_FLAGS"

# Wait for the screen and sound to exist.
for _ in $(seq 1 50); do
    [ -e /tmp/.X11-unix/X99 ] && [ -e /tmp/pulse/native ] && break
    sleep 0.2
done

exec google-chrome-stable "${sandbox[@]}" "${extra[@]}" \
    --user-data-dir="$PROFILE" \
    --no-first-run --no-default-browser-check \
    --password-store=basic \
    --window-position=0,0 --window-size=1920,1100 --start-fullscreen \
    --hide-crash-restore-bubble \
    --autoplay-policy=no-user-gesture-required \
    --disable-features=Translate,MediaRouter \
    --disable-dev-shm-usage \
    --remote-debugging-port=9222 \
    http://127.0.0.1:8080/start
