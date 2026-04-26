#!/usr/bin/env python3
"""AppImage Installer — install AppImages as system applications.

Universal Linux support: detects distro family and privilege-escalation method
at startup and adapts. Works on Debian/Ubuntu, Arch, Fedora/RHEL, openSUSE,
Gentoo, Alpine, Void, and any other distro with a standards-compliant XDG
layout.
"""
import gi, os, sys, json, shutil, subprocess, tempfile, re, urllib.parse, glob, shlex
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

OPT_DIR = "/opt"
BIN_DIR = "/usr/local/bin"
APPS_DIR = "/usr/share/applications"
ICONS_DIR = "/usr/share/icons/hicolor"
MANIFEST_DIR = "/var/lib/appimage-installer"

CONFIG_DIR = os.path.expanduser("~/.config/appimage-installer")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ---------- environment detection ----------

def detect_distro():
    info = {"id": "unknown", "name": "Unknown Linux", "family": "unknown"}
    try:
        d = {}
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    d[k] = v.strip().strip('"')
        info["id"] = d.get("ID", info["id"])
        info["name"] = d.get("PRETTY_NAME", info["id"])
        like = (d.get("ID_LIKE", "") + " " + d.get("ID", "")).lower().split()
        family_map = {
            "debian": "debian", "ubuntu": "debian", "linuxmint": "debian",
            "arch": "arch", "manjaro": "arch", "endeavouros": "arch", "cachyos": "arch",
            "fedora": "fedora", "rhel": "fedora", "centos": "fedora", "rocky": "fedora", "almalinux": "fedora",
            "suse": "suse", "opensuse": "suse", "opensuse-tumbleweed": "suse", "opensuse-leap": "suse", "sled": "suse", "sles": "suse",
            "gentoo": "gentoo",
            "alpine": "alpine",
            "void": "void",
            "nixos": "nixos",
        }
        for token in like:
            if token in family_map:
                info["family"] = family_map[token]
                break
    except Exception:
        pass
    return info


def _sudo_mode():
    try:
        if subprocess.run(["sudo", "-n", "true"], timeout=5,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0:
            return "sudo-nopw"
    except Exception:
        pass
    return "sudo"


def detect_priv():
    if os.geteuid() == 0:
        return "root"

    cfg = load_config()
    override = cfg.get("priv_override", "auto")

    if override == "pkexec" and shutil.which("pkexec"):
        return "pkexec"
    if override == "sudo" and shutil.which("sudo"):
        return _sudo_mode()
    if override == "doas" and shutil.which("doas"):
        return "doas"

    # auto: prefer passwordless sudo, then pkexec for GUI, then prompted sudo, then doas
    if shutil.which("sudo"):
        m = _sudo_mode()
        if m == "sudo-nopw":
            return m
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    if has_display and shutil.which("pkexec"):
        return "pkexec"
    if shutil.which("sudo"):
        return "sudo"
    if shutil.which("doas"):
        return "doas"
    return "none"


DISTRO = detect_distro()
PRIV = detect_priv()


PKG_HINTS = {
    "debian":  "sudo apt install desktop-file-utils libgtk-3-bin python3-gi",
    "arch":    "sudo pacman -S desktop-file-utils gtk3 python-gobject",
    "fedora":  "sudo dnf install desktop-file-utils gtk3 python3-gobject",
    "suse":    "sudo zypper install desktop-file-utils gtk3-tools python3-gobject",
    "gentoo":  "sudo emerge dev-util/desktop-file-utils x11-libs/gtk+ dev-python/pygobject",
    "alpine":  "sudo apk add desktop-file-utils gtk+3.0 py3-gobject3",
    "void":    "sudo xbps-install desktop-file-utils gtk+3 python3-gobject",
    "nixos":   "(NixOS) add desktop-file-utils, gtk3, python3-gobject to your system packages",
}


# ---------- privileged execution ----------

def _ask_password_gtk(reason="apply system changes"):
    """Pop a tiny GTK password dialog. Returns the entered string or None."""
    dlg = Gtk.Dialog(title="Authentication required", modal=True)
    dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                    Gtk.STOCK_OK, Gtk.ResponseType.OK)
    box = dlg.get_content_area()
    box.set_spacing(10)
    box.set_border_width(14)
    msg = Gtk.Label(xalign=0)
    msg.set_markup(f"Enter your password to <b>{GLib.markup_escape_text(reason)}</b>.")
    box.add(msg)
    entry = Gtk.Entry()
    entry.set_visibility(False)
    entry.set_invisible_char("•")
    entry.set_activates_default(True)
    entry.set_width_chars(28)
    box.add(entry)
    dlg.set_default_response(Gtk.ResponseType.OK)
    dlg.show_all()
    entry.grab_focus()
    resp = dlg.run()
    pw = entry.get_text() if resp == Gtk.ResponseType.OK else None
    dlg.destroy()
    while Gtk.events_pending():
        Gtk.main_iteration()
    return pw


def _format_priv_error(rc, stderr, stdout):
    msg = (stderr or stdout or "").strip()
    return f"Privileged step failed (exit {rc}): {msg[-400:]}"


def priv_run(commands, log=None, label="Applying changes"):
    """Run a list of shell commands as root in one batch — single auth prompt."""
    if not commands:
        return
    if PRIV == "none":
        raise RuntimeError("No privilege escalation available. Install sudo, doas, or pkexec.")
    script = "set -e\n" + "\n".join(commands)
    has_tty = sys.stdin.isatty()

    # Modes that don't prompt or that handle prompting themselves (pkexec/polkit)
    if PRIV == "root":
        cmd = ["sh", "-c", script]
    elif PRIV == "sudo-nopw":
        cmd = ["sudo", "-n", "sh", "-c", script]
    elif PRIV == "pkexec":
        if log: log(f"{label} (graphical password prompt)…")
        cmd = ["pkexec", "sh", "-c", script]
    elif PRIV == "sudo" and has_tty:
        if log: log(f"{label} (enter sudo password in terminal)…")
        rc = subprocess.run(["sudo", "sh", "-c", script]).returncode  # no capture
        if rc != 0:
            raise RuntimeError(f"Privileged step failed (exit {rc})")
        return
    elif PRIV == "doas" and has_tty:
        if log: log(f"{label} (enter doas password in terminal)…")
        rc = subprocess.run(["doas", "sh", "-c", script]).returncode
        if rc != 0:
            raise RuntimeError(f"Privileged step failed (exit {rc})")
        return
    elif PRIV == "sudo":
        # GUI session, no pkexec available — ask password ourselves
        pw = _ask_password_gtk(reason=label.lower())
        if pw is None:
            raise RuntimeError("Cancelled by user")
        if log: log(f"{label}…")
        try:
            r = subprocess.run(["sudo", "-S", "-p", "", "sh", "-c", script],
                               input=pw + "\n", capture_output=True, text=True)
        finally:
            del pw
        if r.returncode != 0:
            raise RuntimeError(_format_priv_error(r.returncode, r.stderr, r.stdout))
        return
    elif PRIV == "doas":
        raise RuntimeError(
            "doas can't read passwords from a GUI. Either run from a terminal, "
            "install pkexec, or set 'persist' in /etc/doas.conf."
        )
    else:
        raise RuntimeError(f"Unknown privilege mode: {PRIV}")

    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(_format_priv_error(r.returncode, r.stderr, r.stdout))


def priv_run_best_effort(commands, log=None, label="Refreshing caches"):
    if not commands:
        return
    try:
        priv_run(commands, log, label)
    except Exception as e:
        if log:
            log(f"Note: {label.lower()} skipped ({e})")


# ---------- helpers ----------

def slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "app"


def q(s):
    return shlex.quote(s)


def normalize_path(p):
    if p.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(p).path)
    return p


def list_installed():
    out = []
    if not os.path.isdir(MANIFEST_DIR):
        return out
    for f in sorted(os.listdir(MANIFEST_DIR)):
        if f.endswith(".json"):
            try:
                with open(os.path.join(MANIFEST_DIR, f)) as fp:
                    out.append(json.load(fp))
            except Exception:
                pass
    return out


def parse_desktop(path):
    data = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            in_main = False
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_main = (line == "[Desktop Entry]")
                    continue
                if in_main and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    data.setdefault(k.strip(), v.strip())
    except Exception:
        pass
    return data


def find_icon_source(root, icon_name):
    """Return (src_path, install_size_dir, ext) or None."""
    sized = []
    for ext in ("png", "svg"):
        for path in glob.glob(os.path.join(root, "usr/share/icons/hicolor/*/apps", f"{icon_name}.{ext}")):
            m = re.search(r"/(\d+)x\d+/", path)
            if m:
                sized.append((int(m.group(1)), path, ext))
    if sized:
        sized.sort(reverse=True)
        size, path, ext = sized[0]
        return path, f"{size}x{size}", ext

    for ext in ("png", "svg"):
        path = os.path.join(root, "usr/share/pixmaps", f"{icon_name}.{ext}")
        if os.path.exists(path):
            return path, "256x256", ext

    for ext in ("png", "svg"):
        path = os.path.join(root, f"{icon_name}.{ext}")
        if os.path.exists(path):
            return path, "256x256", ext

    diricon = os.path.join(root, ".DirIcon")
    if os.path.exists(diricon):
        real = os.path.realpath(diricon)
        if real.lower().endswith(".png"):
            return real, "256x256", "png"
        if real.lower().endswith(".svg"):
            return real, "256x256", "svg"
    return None


# ---------- install / uninstall ----------

class AlreadyInstalled(Exception):
    """Raised when the AppImage's app_id is already registered."""


def install_appimage(appimage_path, log, force=False, expected_id=None):
    if not os.path.isfile(appimage_path):
        raise RuntimeError(f"Not a file: {appimage_path}")
    appimage_path = os.path.abspath(appimage_path)
    log(f"Preparing {os.path.basename(appimage_path)}…")
    try:
        os.chmod(appimage_path, 0o755)
    except PermissionError:
        pass

    with tempfile.TemporaryDirectory(prefix="appimg-") as work:
        log("Extracting AppImage…")
        try:
            subprocess.run([appimage_path, "--appimage-extract"], cwd=work,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                           check=True, timeout=180)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                "AppImage extraction failed (may be corrupt or a legacy type-1 image): "
                + (e.stderr or b"").decode(errors="replace")[-300:]
            )
        root = os.path.join(work, "squashfs-root")
        if not os.path.isdir(root):
            raise RuntimeError("Extraction produced no squashfs-root")

        # Pick a .desktop file (or fall back to filename)
        desktops = sorted(glob.glob(os.path.join(root, "*.desktop")))
        if desktops:
            desktop_src = desktops[0]
            d = parse_desktop(desktop_src)
            base_id = os.path.splitext(os.path.basename(desktop_src))[0]
        else:
            log("No .desktop in AppImage; deriving metadata from filename.")
            d = {}
            base_id = re.sub(r"[-_.]\d.*$", "",
                             os.path.splitext(os.path.basename(appimage_path))[0])

        app_id = slug(base_id)
        if expected_id is not None and app_id != expected_id:
            raise RuntimeError(
                f"This AppImage looks like a different app (detected id: '{app_id}'); "
                f"expected '{expected_id}'. Use 'Install' for a new app, or pick the correct file."
            )

        existing_manifest = os.path.join(MANIFEST_DIR, app_id + ".json")
        existed = os.path.exists(existing_manifest)
        if existed and not force:
            try:
                with open(existing_manifest) as f:
                    prev = json.load(f)
                prev_name = prev.get("name", app_id)
                prev_src = prev.get("source", "")
            except Exception:
                prev_name, prev_src = app_id, ""
            extra = f" (originally from {prev_src})" if prev_src else ""
            raise AlreadyInstalled(
                f"\"{prev_name}\" is already installed{extra}.\n"
                f"Uninstall it first, or use the Update button to replace it with a newer version."
            )

        name = d.get("Name", app_id)
        icon_name = d.get("Icon", app_id)
        wm_class = d.get("StartupWMClass", "")
        comment = d.get("Comment", "")
        categories = d.get("Categories", "Utility;")
        mime_types = d.get("MimeType", "")

        target = os.path.join(OPT_DIR, app_id)
        bin_link = os.path.join(BIN_DIR, app_id)
        desktop_path = os.path.join(APPS_DIR, app_id + ".desktop")
        manifest_path = os.path.join(MANIFEST_DIR, app_id + ".json")

        icon_info = find_icon_source(root, icon_name)
        installed_icon = ""
        if icon_info:
            _src, size_dir, ext = icon_info
            installed_icon = os.path.join(ICONS_DIR, size_dir, "apps", f"{icon_name}.{ext}")

        # Build .desktop entry
        lines = [
            "[Desktop Entry]",
            f"Name={name}",
            f"Exec={os.path.join(target, 'AppRun')} %U",
            "Terminal=false",
            "Type=Application",
            f"Icon={icon_name}",
        ]
        if wm_class:   lines.append(f"StartupWMClass={wm_class}")
        if comment:    lines.append(f"Comment={comment}")
        lines.append(f"Categories={categories}")
        if mime_types: lines.append(f"MimeType={mime_types}")
        desktop_text = "\n".join(lines) + "\n"

        tmp_desktop = os.path.join(work, "entry.desktop")
        with open(tmp_desktop, "w") as f:
            f.write(desktop_text)

        manifest = {
            "id": app_id,
            "name": name,
            "source": os.path.basename(appimage_path),
            "files": [target, bin_link, desktop_path] + ([installed_icon] if installed_icon else []),
        }
        tmp_man = os.path.join(work, "manifest.json")
        with open(tmp_man, "w") as f:
            json.dump(manifest, f, indent=2)

        has_sandbox = os.path.exists(os.path.join(root, "chrome-sandbox"))

        cmds = [
            f"rm -rf {q(target)}",
            f"mkdir -p {q(OPT_DIR)} {q(BIN_DIR)} {q(APPS_DIR)} {q(MANIFEST_DIR)}",
            f"cp -a {q(root)} {q(target)}",
            f"chown -R root:root {q(target)}",
            f"chmod -R go+rX {q(target)}",
        ]
        if has_sandbox:
            cmds.append(f"chmod 4755 {q(os.path.join(target, 'chrome-sandbox'))}")
        cmds.append(f"ln -sf {q(os.path.join(target, 'AppRun'))} {q(bin_link)}")
        if installed_icon:
            cmds.append(f"install -Dm644 {q(icon_info[0])} {q(installed_icon)}")
        cmds.append(f"install -Dm644 {q(tmp_desktop)} {q(desktop_path)}")
        cmds.append(f"install -Dm644 {q(tmp_man)} {q(manifest_path)}")
        verb_ing = "Updating" if existed else "Installing"
        priv_run(cmds, log, label=f"{verb_ing} {name}")

        refresh = []
        if shutil.which("update-desktop-database"):
            refresh.append(f"update-desktop-database {q(APPS_DIR)} || true")
        if shutil.which("gtk-update-icon-cache"):
            refresh.append(f"gtk-update-icon-cache -q -t {q(ICONS_DIR)} || true")
        priv_run_best_effort(refresh, log)

        # Post-install sanity check: AppRun must be readable+executable by current user
        apprun = os.path.join(target, "AppRun")
        if not os.access(apprun, os.R_OK | os.X_OK):
            log("Permissions look off after install — re-applying recursive fix…")
            priv_run([f"chmod -R go+rX {q(target)}"], log, label="Fixing permissions")

        log(f"{'Updated' if existed else 'Installed'} {name} ({app_id}) ✓")
        return manifest


def uninstall(app_id, log):
    man_path = os.path.join(MANIFEST_DIR, app_id + ".json")
    if not os.path.exists(man_path):
        raise RuntimeError(f"No manifest for {app_id}")
    with open(man_path) as f:
        man = json.load(f)
    name = man.get("name", app_id)
    cmds = [f"rm -rf {q(p)}" for p in man.get("files", []) if p]
    cmds.append(f"rm -f {q(man_path)}")
    priv_run(cmds, log, label=f"Removing {name}")

    refresh = []
    if shutil.which("update-desktop-database"):
        refresh.append(f"update-desktop-database {q(APPS_DIR)} || true")
    if shutil.which("gtk-update-icon-cache"):
        refresh.append(f"gtk-update-icon-cache -q -t {q(ICONS_DIR)} || true")
    priv_run_best_effort(refresh, log)
    log(f"Uninstalled {name} ✓")


# ---------- GUI ----------

class App(Gtk.Window):
    def __init__(self):
        super().__init__(title="AppImage Installer")
        self.set_default_size(620, 540)
        self.set_border_width(12)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        drop_frame = Gtk.Frame()
        lbl = Gtk.Label()
        lbl.set_markup("<big>Drop an .AppImage here to install</big>\n<small>or click to browse</small>")
        lbl.set_justify(Gtk.Justification.CENTER)
        lbl.set_margin_top(28); lbl.set_margin_bottom(28)
        drop_frame.add(lbl)
        evt = Gtk.EventBox()
        evt.add(drop_frame)
        evt.connect("button-press-event", self.on_browse)
        vbox.pack_start(evt, False, False, 0)

        targets = Gtk.TargetList.new([])
        targets.add_uri_targets(0)
        evt.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        evt.drag_dest_set_target_list(targets)
        evt.connect("drag-data-received", self.on_drop)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.pack_start(Gtk.Label(label="Installed apps", xalign=0), True, True, 0)
        settings_btn = Gtk.Button(label="Settings")
        settings_btn.connect("clicked", self.open_settings)
        header.pack_end(settings_btn, False, False, 0)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda *_: self.refresh())
        header.pack_end(refresh_btn, False, False, 0)
        vbox.pack_start(header, False, False, 0)

        self.listbox = Gtk.ListBox()
        scroll = Gtk.ScrolledWindow(); scroll.set_vexpand(True); scroll.add(self.listbox)
        vbox.pack_start(scroll, True, True, 0)

        self.status = Gtk.Label(label="Ready.", xalign=0)
        self.status.set_line_wrap(True)
        vbox.pack_start(self.status, False, False, 0)

        self.info = Gtk.Label(xalign=0)
        self._update_info()
        vbox.pack_start(self.info, False, False, 0)

        if PRIV == "none":
            self.log("⚠ No privilege escalation available. Install sudo, doas, or pkexec.")
        else:
            missing = []
            if not shutil.which("update-desktop-database"): missing.append("desktop-file-utils")
            if not shutil.which("gtk-update-icon-cache"):   missing.append("gtk-update-icon-cache")
            hint = PKG_HINTS.get(DISTRO["family"])
            if missing and hint:
                self.log(f"Optional helpers missing ({', '.join(missing)}). Hint: {hint}")

        self.refresh()

    def log(self, msg):
        self.status.set_text(msg)
        while Gtk.events_pending():
            Gtk.main_iteration()

    def refresh(self):
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        installs = list_installed()
        if not installs:
            row = Gtk.ListBoxRow()
            l = Gtk.Label(label="(none yet)", xalign=0)
            l.set_margin_top(6); l.set_margin_bottom(6); l.set_margin_start(8)
            row.add(l)
            self.listbox.add(row)
        for man in installs:
            row = Gtk.ListBoxRow()
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hbox.set_margin_top(6); hbox.set_margin_bottom(6)
            hbox.set_margin_start(8); hbox.set_margin_end(8)
            label = Gtk.Label(xalign=0)
            label.set_markup(
                f"<b>{GLib.markup_escape_text(man['name'])}</b>  "
                f"<small>{GLib.markup_escape_text(man['id'])}</small>"
            )
            hbox.pack_start(label, True, True, 0)
            uninstall_btn = Gtk.Button(label="Uninstall")
            uninstall_btn.connect("clicked", self.on_uninstall, man["id"])
            hbox.pack_end(uninstall_btn, False, False, 0)
            update_btn = Gtk.Button(label="Update…")
            update_btn.connect("clicked", self.on_update, man["id"], man.get("name", man["id"]))
            hbox.pack_end(update_btn, False, False, 0)
            row.add(hbox)
            self.listbox.add(row)
        self.listbox.show_all()

    def on_browse(self, *_):
        dlg = Gtk.FileChooserDialog(title="Select AppImage", parent=self,
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        flt = Gtk.FileFilter(); flt.set_name("AppImage")
        flt.add_pattern("*.AppImage"); flt.add_pattern("*.appimage")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            dlg.destroy()
            self.do_install(path)
        else:
            dlg.destroy()

    def on_drop(self, _w, ctx, _x, _y, data, _info, time):
        for uri in data.get_uris():
            path = normalize_path(uri)
            if path.lower().endswith(".appimage"):
                self.do_install(path)
                break
            else:
                self.log(f"Not an AppImage: {path}")
        ctx.finish(True, False, time)

    def do_install(self, path):
        try:
            install_appimage(path, self.log)
            self.refresh()
        except AlreadyInstalled as e:
            self.log("Already installed — see dialog.")
            self._info_dialog("AppImage already installed", str(e),
                              Gtk.MessageType.INFO)
        except Exception as e:
            self.log(f"Error: {e}")
        return False  # for GLib.idle_add

    def _info_dialog(self, primary, secondary, msg_type=Gtk.MessageType.INFO):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=msg_type,
                                buttons=Gtk.ButtonsType.OK,
                                text=primary)
        dlg.format_secondary_text(secondary)
        dlg.run(); dlg.destroy()

    def _update_info(self):
        cfg = load_config()
        override = cfg.get("priv_override", "auto")
        suffix = "" if override == "auto" else f" <i>(forced: {GLib.markup_escape_text(override)})</i>"
        self.info.set_markup(
            f"<small>Distro: <b>{GLib.markup_escape_text(DISTRO['name'])}</b> "
            f"({GLib.markup_escape_text(DISTRO['family'])}) · "
            f"Privilege: <b>{GLib.markup_escape_text(PRIV)}</b>{suffix}</small>"
        )

    def open_settings(self, _btn=None):
        global PRIV
        cfg = load_config()
        current = cfg.get("priv_override", "auto")

        dlg = Gtk.Dialog(title="Settings", modal=True, transient_for=self)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dlg.set_default_size(420, 220)
        box = dlg.get_content_area()
        box.set_spacing(10); box.set_border_width(14)

        box.add(Gtk.Label(label="Privilege escalation method:", xalign=0))
        combo = Gtk.ComboBoxText()
        options = [
            ("auto",   "Automatic (recommended)"),
            ("pkexec", "Always use pkexec (polkit GUI prompt)"),
            ("sudo",   "Always use sudo"),
            ("doas",   "Always use doas"),
        ]
        sel = 0
        for i, (k, lbl) in enumerate(options):
            combo.append(k, lbl)
            if k == current:
                sel = i
        combo.set_active(sel)
        box.add(combo)

        avail = [t for t in ("sudo", "doas", "pkexec") if shutil.which(t)] or ["(none)"]
        hint = Gtk.Label(xalign=0)
        hint.set_line_wrap(True)
        hint.set_markup(
            f"<small>Available on this system: <b>{', '.join(avail)}</b>. "
            f"If a forced method is unavailable, the installer falls back to automatic.</small>"
        )
        box.add(hint)

        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            choice = combo.get_active_id() or "auto"
            cfg["priv_override"] = choice
            save_config(cfg)
            PRIV = detect_priv()
            self._update_info()
            self.log(f"Privilege mode is now: {PRIV}"
                     + ("" if choice == "auto" else f" (forced: {choice})"))
        dlg.destroy()

    def on_uninstall(self, _btn, app_id):
        try:
            uninstall(app_id, self.log)
            self.refresh()
        except Exception as e:
            self.log(f"Error: {e}")

    def on_update(self, _btn, app_id, app_name):
        dlg = Gtk.FileChooserDialog(
            title=f"Select new AppImage for {app_name}", parent=self,
            action=Gtk.FileChooserAction.OPEN)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        flt = Gtk.FileFilter(); flt.set_name("AppImage")
        flt.add_pattern("*.AppImage"); flt.add_pattern("*.appimage")
        dlg.add_filter(flt)
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy(); return
        path = dlg.get_filename()
        dlg.destroy()
        try:
            install_appimage(path, self.log, force=True, expected_id=app_id)
            self.refresh()
        except Exception as e:
            self.log(f"Error: {e}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = [normalize_path(a) for a in args if a.lower().endswith(".appimage")]

    if "--cli" in sys.argv:
        force = "--force" in sys.argv
        if not paths:
            print("usage: appimage-installer --cli [--force] FILE.AppImage [...]",
                  file=sys.stderr)
            sys.exit(2)
        for p in paths:
            try:
                install_appimage(p, lambda m: print(m), force=force)
            except AlreadyInstalled as e:
                print(f"Skipped: {e}")
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr); sys.exit(1)
        return

    win = App()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    if paths:
        GLib.idle_add(win.do_install, paths[0])
    Gtk.main()


if __name__ == "__main__":
    main()
