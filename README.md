# BlernsBoard

A single HTML file that reads TensorBoard event logs (`events.out.tfevents.*`)
straight from a directory served by any static file server, and plots them
better than TensorBoard: dark mode, validated run colours, every logged point
kept, robust axis scaling, one tooltip for all runs, restart-aware merging.

No backend, no build, no dependencies. Works with anything that writes the
TensorBoard format: PyTorch `SummaryWriter`, tensorboardX, Lightning,
Hugging Face `Trainer`, Keras, TensorFlow 1 and 2, JAX loggers.

## Run it

Option 1, any static server. Copy the page into the log directory and serve it:

```sh
cp blernsboard.html /path/to/logs/
cd /path/to/logs && python3 -m http.server --bind 0.0.0.0 6006
# open http://<host>:6006/blernsboard.html
```

Option 2, the bundled helper. Nothing is copied, event-file tailing uses HTTP
Range requests, and browser console errors are echoed to the terminal:

```sh
python3 serve.py /path/to/logs --bind 0.0.0.0 --port 6006
# open http://<host>:6006/
```

The page can also be served from elsewhere and pointed at a directory on the
same server with `?logdir=/some/path/`. Runs are discovered by walking the
server's directory listings; a run is any directory containing a file whose
name includes `tfevents`, named by its path relative to the root, exactly as
TensorBoard names it.

## What it shows

- **Scalars**: one chart per tag, grouped by the prefix before the first `/`,
  all selected runs overlaid. Smoothing (TensorBoard's debiased EMA) with the
  raw line kept faint behind it. X axis in steps, relative time or wall clock.
  Linear or log Y, globally and per chart. Drag to zoom, double-click or
  Escape to reset, optional zoom sync across charts. Pin charts to the top,
  expand one to full width, download the visible data as CSV.
- **Histograms**: a step × value heatmap per run, brighter where the mass is.
- **Text**: latest text with a step slider.
- Runs list with regex filter, all/none/invert, alt-click to solo, hover to
  highlight that run in every chart, double-click the swatch to change colour.
- Auto refresh (5s to 60s or off) that only fetches what grew. State lives in
  the URL hash and is remembered per log directory.

Images, audio, hparams, graphs and the profiler are not shown. The run's
tooltip in the sidebar reports how many such summaries were skipped.

## Reading the format exactly

Files are TFRecords (length, masked CRC-32C, payload, masked CRC-32C), each
payload a protobuf `Event`. Both CRCs are verified; a bad record stops that
file and flags the run with the byte offset. Scalars are read from
`simple_value` (PyTorch, TF1) and from `TensorProto` (TF2), histograms from
`HistogramProto` and from `[k,3]` tensors, text from string tensors.

When a trainer resumes from a checkpoint and re-logs steps, the older copy of
each overwritten step is dropped per series, so restarts do not draw zigzags.
`keep overwritten points` turns this off.

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install tensorboard playwright
.venv/bin/python tools/make_demo_logs.py demo_logs      # realistic fixture logdir
node tools/check_parser.mjs demo_logs                    # reader vs ground truth
node tools/check_tail.mjs demo_logs                      # incremental refresh
.venv/bin/python -m playwright install chromium-headless-shell
.venv/bin/python tools/shot.py http://127.0.0.1:6006/ out --actions hover,smooth,log
```

See `DESIGN.md` for the design document: goals, feature valuation, layout,
chart rules, failure states and what was deliberately left out.
