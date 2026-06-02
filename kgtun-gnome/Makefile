# Makefile — Kaggle Instance Manager GNOME Extension
UUID = kgtun-manager@hamimmahmud0
EXT_DIR = $(HOME)/.local/share/gnome-shell/extensions/$(UUID)

all: install

install:
	mkdir -p $(EXT_DIR)
	cp -r metadata.json extension.js prefs.js stylesheet.css schemas $(EXT_DIR)/
	glib-compile-schemas $(EXT_DIR)/schemas/
	@echo "Extension installed to $(EXT_DIR)"
	@echo "Restart GNOME Shell (Alt+F2, r, Enter) or log out/in to activate."
	@echo "Then enable via: gnome-extensions enable $(UUID)"

uninstall:
	rm -rf $(EXT_DIR)
	@echo "Extension uninstalled."

zip:
	cd .. && \
	zip -r kgtun-gnome.zip kgtun-gnome/metadata.json kgtun-gnome/extension.js \
		kgtun-gnome/prefs.js kgtun-gnome/stylesheet.css \
		kgtun-gnome/schemas/ && \
	mv kgtun-gnome.zip kgtun-gnome/
	@echo "Created kgtun-gnome.zip for manual installation"

.PHONY: all install uninstall zip
