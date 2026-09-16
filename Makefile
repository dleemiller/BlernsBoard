# Install BlernsBoard as a shell command without pip.
#   make install              -> ~/.local/share/blernsboard + ~/.local/bin/blernsboard
#   make install PREFIX=/usr/local   (system-wide, may need sudo)
#   make uninstall
PREFIX ?= $(HOME)/.local
BIN    := $(PREFIX)/bin
SHARE  := $(PREFIX)/share/blernsboard
PYTHON := $(shell command -v python3 || command -v python)

.PHONY: install uninstall check

install: check
	@mkdir -p "$(SHARE)" "$(BIN)"
	@cp blernsboard.html serve.py "$(SHARE)/"
	@printf '#!/bin/sh\nexec "%s" "%s/serve.py" "$$@"\n' "$(PYTHON)" "$(SHARE)" > "$(BIN)/blernsboard"
	@chmod +x "$(BIN)/blernsboard"
	@echo "installed: $(BIN)/blernsboard  (files in $(SHARE))"
	@case ":$$PATH:" in *":$(BIN):"*) ;; *) echo; echo "note: $(BIN) is not on your PATH. Add this to your shell rc (~/.bashrc or ~/.zshrc):"; echo '  export PATH="$(BIN):$$PATH"';; esac

uninstall:
	@rm -f "$(BIN)/blernsboard"
	@rm -rf "$(SHARE)"
	@echo "removed $(BIN)/blernsboard and $(SHARE)"

check:
	@test -n "$(PYTHON)" || { echo "python3 not found"; exit 1; }
	@"$(PYTHON)" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' || { echo "python >= 3.8 required"; exit 1; }
