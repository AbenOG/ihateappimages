#!/usr/bin/env bash
# AppImage Installer — bootstrap installer
# Usage: curl -fsSL https://raw.githubusercontent.com/AbenOG/ihateappimages/main/install.sh | bash
#    or: ./install.sh
set -euo pipefail

REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/AbenOG/ihateappimages/main}"
PREFIX="${PREFIX:-/opt/appimage-installer}"

# ---- distro detection (for dependency hints only) ----
distro_id="unknown"
distro_like=""
if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    distro_id="${ID:-unknown}"
    distro_like="${ID_LIKE:-} ${ID:-}"
fi

dep_hint() {
    case " $distro_like " in
        *" debian "*|*" ubuntu "*) echo "sudo apt install python3-gi gir1.2-gtk-3.0 desktop-file-utils";;
        *" arch "*)                echo "sudo pacman -S python-gobject gtk3 desktop-file-utils";;
        *" fedora "*|*" rhel "*)   echo "sudo dnf install python3-gobject gtk3 desktop-file-utils";;
        *" suse "*|*" opensuse "*) echo "sudo zypper install python3-gobject gtk3 desktop-file-utils";;
        *" gentoo "*)              echo "sudo emerge dev-python/pygobject x11-libs/gtk+ dev-util/desktop-file-utils";;
        *" alpine "*)              echo "sudo apk add py3-gobject3 gtk+3.0 desktop-file-utils";;
        *)                         echo "(install python3-gi/PyGObject + GTK3 + desktop-file-utils for your distro)";;
    esac
}

# ---- check Python + GTK3 bindings ----
if ! python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
    echo "Missing dependency: python3-gi (PyGObject + GTK3)"
    echo "Install with: $(dep_hint)"
    exit 1
fi

# ---- choose privilege tool ----
if [ "$(id -u)" -eq 0 ]; then
    SUDO=()
elif command -v sudo >/dev/null 2>&1; then
    SUDO=(sudo)
elif command -v doas >/dev/null 2>&1; then
    SUDO=(doas)
elif command -v pkexec >/dev/null 2>&1; then
    SUDO=(pkexec)
else
    echo "Need one of: sudo, doas, pkexec" >&2
    exit 1
fi

# ---- locate sources: prefer local checkout, fall back to download ----
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd 2>/dev/null || pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if [ -f "$script_dir/src/appimage-installer.py" ] && [ -f "$script_dir/share/appimage-installer.desktop" ]; then
    echo "Using local sources from $script_dir"
    cp "$script_dir/src/appimage-installer.py" "$tmp/app.py"
    cp "$script_dir/share/appimage-installer.desktop" "$tmp/appimage-installer.desktop"
else
    echo "Downloading sources from $REPO_RAW…"
    curl -fsSL "$REPO_RAW/src/appimage-installer.py"          -o "$tmp/app.py"
    curl -fsSL "$REPO_RAW/share/appimage-installer.desktop"   -o "$tmp/appimage-installer.desktop"
fi

# ---- write wrapper ----
cat >"$tmp/appimage-installer" <<EOF
#!/bin/sh
exec python3 "$PREFIX/app.py" "\$@"
EOF
chmod 755 "$tmp/appimage-installer"

# ---- install (single privileged batch) ----
echo "Installing to $PREFIX (privileged)…"
"${SUDO[@]}" sh -c "
set -e
install -Dm755 '$tmp/app.py'                  '$PREFIX/app.py'
install -Dm755 '$tmp/appimage-installer'      /usr/local/bin/appimage-installer
install -Dm644 '$tmp/appimage-installer.desktop' /usr/share/applications/appimage-installer.desktop
mkdir -p /var/lib/appimage-installer
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
command -v gtk-update-icon-cache    >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
"

cat <<EOF

✓ AppImage Installer is installed.

  Launch from terminal: appimage-installer
  Launch from menu:     search "AppImage Installer"

To uninstall later, run: appimage-installer-uninstall  (or use uninstall.sh from the repo)
EOF
