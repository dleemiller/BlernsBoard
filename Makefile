# make install               interactive: asks for the prefix (default ~/.local) and before overwriting
# make install PREFIX=/opt   non-interactive prefix, still asks before overwriting
# make uninstall [PREFIX=..]
# FORCE=1 make install PREFIX=~/.local   no prompts at all (scripts, CI)
.PHONY: install uninstall

install:
	@sh install.sh $(if $(PREFIX),--prefix "$(PREFIX)")

uninstall:
	@sh install.sh --uninstall $(if $(PREFIX),--prefix "$(PREFIX)")
