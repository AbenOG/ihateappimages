#!/usr/bin/env bash
# AppImage Installer — uninstall script
# Removes the installer itself. Apps you installed are kept;
# uninstall them through the GUI first if you want them gone.
set -euo pipefail

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

PREFIX="${PREFIX:-/opt/appimage-installer}"
KEEP_MANIFESTS="${KEEP_MANIFESTS:-1}"

leftover_apps=$(ls /var/lib/appimage-installer/*.json 2>/dev/null | wc -l || echo 0)
if [ "$leftover_apps" -gt 0 ] && [ "$KEEP_MANIFESTS" = "1" ]; then
    echo "Note: $leftover_apps installed apps are still tracked."
    echo "      Open the installer to uninstall them first if you want to remove them too."
    echo "      (Set KEEP_MANIFESTS=0 to wipe the manifest dir as well.)"
fi

echo "Removing AppImage Installer (privileged)…"
"${SUDO[@]}" sh -c "
set -e
rm -rf '$PREFIX'
rm -f /usr/local/bin/appimage-installer
rm -f /usr/share/applications/appimage-installer.desktop
[ '$KEEP_MANIFESTS' = '0' ] && rm -rf /var/lib/appimage-installer || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications || true
"
echo "✓ Uninstalled."
