#!/usr/bin/env bash
# Shabbat Display setup for Raspberry Pi OS (Bookworm or newer, with desktop).
# Also works on other Debian/Ubuntu desktops; the Pi-only steps are skipped there.
# Run it from this folder as your normal user:   bash setup-pi.sh
# It is safe to run again at any time.
#
#   1. Checks Python 3 and installs Chromium if needed.
#   2. Creates settings.json from settings.example.json.
#   3. Sets the system time zone to the one in settings.json.
#   4. Tests every data source.
#   5. Boots to the desktop and logs in automatically, with screen blanking off.
#   6. Makes the display start at login.

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
ask() { local a; read -r -p "$1 [Y/n] " a; [[ -z "$a" || "$a" =~ ^[Yy] ]]; }

if [[ $EUID -eq 0 ]]; then
    echo "Run this as your normal user, not with sudo. It asks for your password when it needs to."
    exit 1
fi

echo "Shabbat Display setup"
echo "Folder: $HERE"

# ------------------------------------------------------------------ Python
step "Python"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    echo "Installing Python 3..."
    sudo apt-get update && sudo apt-get install -y python3 || { warn "Could not install Python 3."; exit 1; }
fi
python3 --version

# ------------------------------------------------------------------ Browser
step "Browser"
browser=""
for b in chromium chromium-browser google-chrome google-chrome-stable; do
    if command -v "$b" >/dev/null; then browser="$(command -v "$b")"; break; fi
done
if [[ -z "$browser" ]]; then
    echo "Installing Chromium..."
    sudo apt-get update
    sudo apt-get install -y chromium || sudo apt-get install -y chromium-browser
    for b in chromium chromium-browser; do
        if command -v "$b" >/dev/null; then browser="$(command -v "$b")"; break; fi
    done
fi
if [[ -z "$browser" ]]; then warn "Could not install Chromium."; exit 1; fi
echo "Using $browser"

# ------------------------------------------------------------------ Settings
step "Settings"
chmod +x start-display.sh stop-display.sh check-feeds.sh 2>/dev/null
if [[ -f settings.json ]]; then
    echo "settings.json already exists; leaving it as is."
else
    cp settings.example.json settings.json
    echo "Created settings.json (Teaneck, NJ). Edit it to change location, dimming and so on."
fi

# ------------------------------------------------------------------ Time zone
step "Time zone"
want="$(python3 server.py --setting tzid)"
have="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null)"
if [[ -n "$want" && "$want" != "$have" ]]; then
    echo "The clock and zmanim need the system time zone to match settings.json."
    if ask "Change the time zone from ${have:-unknown} to $want?"; then
        sudo timedatectl set-timezone "$want" && echo "Time zone set to $want."
    fi
else
    echo "Time zone is $have."
fi

# ------------------------------------------------------------------ Feeds
step "Testing the data sources (takes about a minute)"
python3 server.py --check
echo "One or two failures are usually a slow connection. The display retries on its own."

# ------------------------------------------------------------------ Desktop
step "Desktop login and screen blanking"
if command -v raspi-config >/dev/null; then
    if ask "Boot straight to the desktop and log in automatically?"; then
        sudo raspi-config nonint do_boot_behaviour B4 && echo "Done."
    fi
    if ask "Turn off screen blanking so the screen never goes dark?"; then
        sudo raspi-config nonint do_blanking 1 && echo "Done."
    fi
else
    echo "Not a Raspberry Pi. Set these in your desktop's settings:"
    echo " - log in automatically"
    echo " - never blank the screen, turn it off, or lock it"
    echo " - never suspend"
fi

# ------------------------------------------------------------------ Autostart
step "Start automatically"
autostart="$HOME/.config/autostart/shabbat-display.desktop"
if ask "Start the display every time the desktop starts?"; then
    mkdir -p "$(dirname "$autostart")"
    cat > "$autostart" <<EOF
[Desktop Entry]
Type=Application
Name=Shabbat Display
Comment=Full-screen Shabbat, zmanim, weather, Yankees and news display
Exec=$(command -v python3) "$HERE/launcher.pyw"
X-GNOME-Autostart-enabled=true
EOF
    echo "Added $autostart"
fi

# ------------------------------------------------------------------ Done
step "Finished"
echo "To start it now from the Pi's desktop: ./start-display.sh   (stop it with ./stop-display.sh)"
echo "To see it from another computer, set \"bind\": \"0.0.0.0\" in settings.json."
if [[ -f "$autostart" ]] && ask "Reboot now to check that it comes up on its own?"; then
    sudo reboot
fi
