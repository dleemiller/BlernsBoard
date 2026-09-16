# BlernsBoard

A single HTML file that reads TensorBoard event logs

## Run it

```sh
cp blernsboard.html /path/to/logs/
cd /path/to/logs && python3 -m http.server --bind 0.0.0.0 6006
# open http://<host>:6006/blernsboard.html
```

Option 2

```sh
python3 serve.py /path/to/logs --bind 0.0.0.0 --port 6006
# open http://<host>:6006/
```

The page can also be served from elsewhere and pointed at a directory on the
same server with `?logdir=/some/path/`. Runs are discovered by walking the
server's directory listings; a run is any directory containing a file whose
name includes `tfevents`, named by its path relative to the root, exactly as
TensorBoard names it.

