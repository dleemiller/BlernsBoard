# BlernsBoard

A single HTML file that reads TensorBoard event logs

## Install

Any of these gives you a `blernsboard` command. Python 3.8+ is the only requirement; there are no dependencies.

```sh
pipx install git+https://github.com/dleemiller/BlernsBoard      # or: pip install git+...
```

```sh
git clone https://github.com/dleemiller/BlernsBoard && cd BlernsBoard
make install
```

`make install` asks `Install to ~/.local? [Y/n]` (that gives `~/.local/bin/blernsboard`), says so if it would replace an existing install, and stops on `n` or Ctrl-C without touching anything. Use `make install PREFIX=/usr/local` for another location and `make uninstall` to remove it. It tells you if the bin directory is not on your PATH, which is common on macOS.

## Run it

Flags follow TensorBoard's names:

```sh
blernsboard --logdir runs/                  # http://localhost:6006/
blernsboard --logdir runs/ --bind_all       # reachable from other machines
blernsboard runs/ --port 8080 --open        # positional logdir, open a browser
```

Without installing anything, the page also works with any static server. Copy it into the log directory and serve it:

```sh
cp blernsboard.html /path/to/logs/
cd /path/to/logs && python3 -m http.server --bind 0.0.0.0 6006
# open http://<host>:6006/blernsboard.html
```

Or run the helper from the checkout: `python3 serve.py --logdir /path/to/logs --bind_all`.

The page can also be served from elsewhere and pointed at a directory on the
same server with `?logdir=/some/path/`. Runs are discovered by walking the
server's directory listings; a run is any directory containing a file whose
name includes `tfevents`, named by its path relative to the root, exactly as
TensorBoard names it.

