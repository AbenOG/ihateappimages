# AppImage Installer

A small GTK app that turns any `.AppImage` into a real system application. Drag and drop, click install, get a menu entry. Uninstall and update with one click.

No more random AppImages cluttering your Downloads folder.

---

## Install (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/AbenOG/ihateappimages/main/install.sh | bash
```

Replace `AbenOG/ihateappimages` with the actual GitHub path. The installer detects your distro, checks dependencies, and asks for your password once.

### Or clone and run

```bash
git clone https://github.com/AbenOG/ihateappimages.git
cd REPO
./install.sh           # quick install
# or
sudo make install      # traditional install
```

---

## What you get

- Drag-and-drop install of any AppImage to `/opt/<app>` with a real `.desktop` entry, icon, and `/usr/local/bin/<app>` launcher
- **Update** button per app: pick the new AppImage, it replaces the old install in place
- **Uninstall** button: cleanly removes everything the installer added
- **Settings**: force `pkexec` / `sudo` / `doas`, or auto-detect
- Works on **Debian/Ubuntu/Mint, Arch/Manjaro, Fedora/RHEL, openSUSE, Gentoo, Alpine, Void** and any other distro with a standard XDG layout
- Single auth prompt per operation (all root commands are batched)
- Recursive permission fix on every install (so apps actually launch — yes, this is a real AppImage gotcha)
- Sets `chrome-sandbox` setuid for Electron apps automatically
- Duplicate detection — won't silently overwrite an existing install
- Works as a CLI too: `appimage-installer --cli /path/to/foo.AppImage`

---

## Requirements

- Python 3 with PyGObject (`python3-gi`)
- GTK 3
- One of: `sudo`, `doas`, `pkexec` (for the privileged install steps)

`install.sh` will tell you the exact package command for your distro if anything is missing.

---

## CLI usage

```bash
appimage-installer                              # open the GUI
appimage-installer foo.AppImage                 # GUI with auto-install on launch
appimage-installer --cli foo.AppImage           # headless install
appimage-installer --cli --force foo.AppImage   # force reinstall / update
```

---

## Uninstall

```bash
./uninstall.sh
# or
sudo make uninstall
```

Apps you installed through the GUI are **kept** by default. Open the installer first and uninstall them through the UI if you want them gone, or run `KEEP_MANIFESTS=0 ./uninstall.sh` to wipe everything including the manifest dir.

---

## Layout

| Path | Purpose |
|---|---|
| `/opt/<app_id>/` | extracted AppImage contents |
| `/usr/local/bin/<app_id>` | symlink to AppRun |
| `/usr/share/applications/<app_id>.desktop` | menu entry |
| `/usr/share/icons/hicolor/<size>/apps/<icon>.png` | icon |
| `/var/lib/appimage-installer/<app_id>.json` | install manifest (used for clean uninstall) |
| `~/.config/appimage-installer/config.json` | per-user settings (priv override) |

---

## License

See [LICENSE](LICENSE).
