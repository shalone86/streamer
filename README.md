# Streamer

Watch Netflix, Peacock, Tubi and Sling on a Roku through an ad-blocking browser.

The server (a Docker container on Unraid) runs Chrome with AdGuard on a virtual
screen and turns that screen into a video stream. A homebrew Roku channel plays
the stream and sends your remote's buttons back to the browser.

```
Roku remote → Streamer channel ──(buttons)──→ server
                     ↑                            │
                     └──── video (HLS) ── ffmpeg ← Chrome + AdGuard
```

Status: **stage 1**, the stream and remote control. Next up is a Netflix-style
home screen with rows of shows.

## 1. Install on Unraid

The image is built by GitHub Actions and published as
`ghcr.io/shalone86/streamer:latest`.

1. **Once, after the first build:** on GitHub open your profile → **Packages** →
   **streamer** → **Package settings** → **Change visibility** → **Public**, so
   Unraid can download it without logging in.
2. In the Unraid web UI, open **Terminal** (top right) and run:
   ```
   wget -O /boot/config/plugins/dockerMan/templates-user/my-streamer.xml \
     https://raw.githubusercontent.com/shalone86/streamer/main/unraid/streamer.xml
   ```
3. **Docker** tab → **Add Container** → **Template:** choose `streamer`.
4. Set a **Browser view password**. Anyone on your network who can open the
   browser view can use your logged-in accounts.
5. If port 8080 is already taken (qBittorrent, SABnzbd…), change **Control port**
   to something free like 8095. **Apply.**

## 2. Log in to your services

Open `http://<server-ip>:8080`. That's the setup page; Unraid's **WebUI** button
on the container goes there too.

- **Open the browser view**: the server's Chrome, in your browser. Log in to
  Netflix, Peacock and Tubi. The logins are kept in `/mnt/user/appdata/streamer`.
  Sling opens on its free movies and shows (Freestream), which need no login.
- Check that AdGuard is on: press F11 to leave full screen, click the
  puzzle-piece icon at the top right, and pin AdGuard. Press F11 again to go back.

## 3. Put the channel on the Roku

1. **Developer mode:** on the Roku remote press **Home ×3, Up ×2, Right, Left,
   Right, Left, Right**. Note the address it shows, choose **Enable installer
   and restart**, accept the agreement, and set a password.
2. On the setup page, check the server address (use the IP, like
   `http://192.168.1.10:8080`) and press **Download Roku channel**. The address
   is built into the channel.
3. On a computer, open the address the Roku showed (like `http://192.168.1.50`),
   log in as `rokudev` with the password from step 1, choose the zip, and press
   **Install**. **Streamer** appears on the Roku home screen.

Sideloaded channels stay installed until you replace them. Only one sideloaded
channel at a time.

## Using it

The home screen shows what's on Netflix, Peacock, Tubi and Sling's free movies
and shows, in rows by genre (Popular, Comedy, Action...), and you move around it
like any Roku channel. The top row has **Search** and the services themselves.
Pick a title and it opens in its service, starts, and fills the screen. The
list comes from JustWatch (Netflix, Peacock, Tubi) and Sling's On Demand pages,
is kept in `/config/catalog.json`, and is refreshed twice a day.

Once a video is on, everything you press arrives on screen 2–4 seconds later,
so press once and wait. Hold **Back** to return to the home screen.

| Button | Keyboard mode (default) | Mouse mode |
|---|---|---|
| Arrows | arrow keys | move the pointer (hold to speed up) |
| OK | Enter | click |
| Play/Pause | pause / play the video | same |
| Rewind / Fast-fwd | back / ahead 10 seconds (on a page without a video: previous / next button, Shift+Tab / Tab) | scroll up / down |
| Replay ↺ | full screen (`f`) | Esc (leave full screen, close popups) |
| ✱ | switch to mouse mode | switch to keyboard mode |
| Back | browser Back | browser Back |
| **Hold Back** | return to the channel's menu | same |

Mouse mode is the fallback for anything the keyboard can't reach. To change the
buttons, put a `keymap.json` in `/mnt/user/appdata/streamer` with only the
buttons you want to change (same format as `server/keymap.json`). It's read on
every press, so no restart is needed.

The stream stops by itself 45 seconds after the Roku stops watching.

## Settings (container variables)

| Variable | Default | |
|---|---|---|
| `VNC_PASSWORD` | (none) | password for the browser view |
| `RESOLUTION` | `1920x1080` | `1280x720` uses less CPU and Wi-Fi |
| `BITRATE` | `6M` | lower to `4M` if the Roku buffers |
| `PRESET` | `veryfast` | `superfast` uses less CPU |
| `FPS` | `30` | |
| `HLS_TIME` | `1` | seconds per video segment; `2` is steadier on weak Wi-Fi, but adds delay |
| `IDLE_STOP` | `45` | seconds before an unwatched stream stops |
| `CHROME_FLAGS` | | extra Chrome flags |
| `CHROME_NO_SANDBOX` | | `1` if Chrome won't start without `seccomp=unconfined` |

## Troubleshooting

- **The channel says it can't reach the server.** Use the server's IP address,
  not its name. On the channel's menu choose **Server address...** to change it.
- **Black picture:** check the same page in the browser view. If it's black
  there too, the service refused to play.
- **Stutters on the Roku:** lower `BITRATE` to `4M`, or set `HLS_TIME` to `2`.
- **Logs:** Unraid Docker tab → streamer → **Logs**.

## Keep it at home

This is for your own TV, on your own network. Don't forward these ports to the
internet: the stream and the controls have no login. Using a service through a
setup like this may go against its terms of use.

## How it's built

- `Dockerfile`, `rootfs/`: Debian with Xvfb (1920×1100; the stream is the middle
  1920×1080, so the pointer can hide in the strips), openbox, PulseAudio (a
  virtual sound card), Chrome (AdGuard force-installed by policy), x11vnc +
  noVNC, all run by supervisord.
- `server/streamer.py`: the control server (Python, standard library plus
  `websocket`). It opens pages over Chrome's DevTools port, presses keys with
  xdotool, and runs ffmpeg (x11grab + pulse → H.264/AAC HLS, 1 s segments).
- `roku/`: the SceneGraph channel. `MainScene` has the menu and plays the
  stream, and `ApiTask` sends requests to the server in order.
