PREFIX  ?= /opt/appimage-installer
DESTDIR ?=

BINDIR   = $(DESTDIR)/usr/local/bin
APPSDIR  = $(DESTDIR)/usr/share/applications
DATADIR  = $(DESTDIR)/var/lib/appimage-installer

.PHONY: install uninstall help

help:
	@echo "Targets:"
	@echo "  make install     install to $(PREFIX) (use sudo)"
	@echo "  make uninstall   remove the installer (apps you added are kept)"

install:
	install -Dm755 src/appimage-installer.py $(DESTDIR)$(PREFIX)/app.py
	install -Dm644 share/appimage-installer.desktop $(APPSDIR)/appimage-installer.desktop
	mkdir -p $(BINDIR)
	printf '#!/bin/sh\nexec python3 "%s/app.py" "$$@"\n' "$(PREFIX)" > $(BINDIR)/appimage-installer
	chmod 755 $(BINDIR)/appimage-installer
	mkdir -p $(DATADIR)
	-command -v update-desktop-database >/dev/null && update-desktop-database $(APPSDIR) || true
	@echo "✓ Installed. Run: appimage-installer"

uninstall:
	rm -rf $(DESTDIR)$(PREFIX)
	rm -f  $(BINDIR)/appimage-installer
	rm -f  $(APPSDIR)/appimage-installer.desktop
	-command -v update-desktop-database >/dev/null && update-desktop-database $(APPSDIR) || true
	@echo "✓ Uninstalled (manifests in $(DATADIR) kept; uninstall apps from GUI first if needed)"
