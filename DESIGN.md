# BlernsBoard design

A single HTML file that reads TensorBoard event logs straight from a directory
served by any static file server, and shows them better than TensorBoard does.

## 1. Goals and non-goals

Goals

- One file, no build, no dependencies, no backend. Copy it into a log directory,
  run `python3 -m http.server --bind 0.0.0.0 6006`, open it.
- Byte-exact compatibility with the `tfevents` format written by TensorFlow,
  PyTorch (`torch.utils.tensorboard`), tensorboardX, Lightning, HF `Trainer`,
  Keras, JAX loggers. Anything that writes `events.out.tfevents.*` works.
- Faster to read than TensorBoard: better colour, better axis scaling, no
  silent subsampling, readable at 30 charts on one screen.
- Robust under real conditions: files still being written, restarts from
  checkpoints, corrupt tails, hundreds of runs, millions of points.

Non-goals

- Graph, profiler, embedding projector, PR curves, mesh, debugger. These are
  separate products bolted onto TensorBoard. Not building them.
- Editing or writing logs. Read only.
- Multi-user state. State lives in the URL and the browser.

## 2. Deployment model

The page must be same-origin with the log directory, because plain static
servers do not send CORS headers. Two supported setups:

1. Drop `blernsboard.html` into the log directory. Open
   `http://host:6006/blernsboard.html`. The log root is the page's own
   directory.
2. Serve it from anywhere and point it at a root with `?logdir=/some/path/`
   (same origin) or a full URL (needs CORS on that server).

`serve.py` is an optional 60-line helper that serves the page at `/` and the
log directory beneath it, adds HTTP Range support so tailing is cheap, and
binds all interfaces. It is a convenience, never a requirement.

### Run discovery

Static servers expose directory listings as HTML with `<a href>` links. Python,
nginx autoindex, Caddy, `npx serve`, busybox httpd all do. The page fetches the
root listing, parses every anchor, treats hrefs ending in `/` as directories
and recurses breadth-first (depth limit 10, concurrency 6, hidden directories
skipped). A run is a directory that contains at least one file whose name
includes `tfevents`. The run name is the directory path relative to the root,
or `.` for the root itself. This matches TensorBoard's naming exactly, so
bookmarks and habits carry over.

If the root returns no parseable listing, the page shows one full-screen card
with the exact command to fix it. No spinner, no empty grid.

### Refresh

Every N seconds (default 15, selectable 5/15/30/60/off, plus a manual button)
the page re-lists directories and, for each known file, sends a `HEAD`. If
`Content-Length` grew, it requests `Range: bytes=<old>-`. A `206` appends; a
`200` (Python's server ignores Range) is sliced at the old offset and appended.
Partial trailing records are held in a buffer until the next refresh. Charts
keep their previous render during a fetch; nothing flashes or jumps.

## 3. File format, read exactly

A `tfevents` file is a sequence of TFRecords, little-endian:

    uint64 length
    uint32 masked_crc32c(length bytes)
    byte   data[length]
    uint32 masked_crc32c(data)

`masked_crc = ((crc >> 15) | (crc << 17)) + 0xa282ead8`, CRC-32C (Castagnoli).
Both CRCs are verified. A failed CRC stops that file and marks the run with a
warning glyph and byte offset. A short read at the end of file is not an
error, it is a writer mid-record.

Each `data` is a protobuf `Event`:

| field | type | use |
|---|---|---|
| 1 wall_time | double | wall clock axis |
| 2 step | int64 | step axis |
| 3 file_version | string | first record, `brain.Event:2` |
| 5 summary | Summary | the payload |
| 7 session_log | SessionLog | `START` (1) signals a restart |

`Summary.value` (1, repeated) is `Summary.Value`:

| field | type | use |
|---|---|---|
| 1 tag | string | series name |
| 2 simple_value | float | scalar (PyTorch, TF1, tensorboardX) |
| 4 image | Image | deferred |
| 5 histo | HistogramProto | histogram (TF1 style) |
| 8 tensor | TensorProto | scalar/histogram/text (TF2 style) |
| 9 metadata | SummaryMetadata | `plugin_data.plugin_name` decides the kind |

`TensorProto`: `dtype` (1), `tensor_shape` (2, dims in field 2 with `size` in
field 1), `tensor_content` (4, raw LE bytes), `float_val` (5, packed),
`double_val` (6), `int_val` (7), `string_val` (8), `int64_val` (10),
`half_val` (13), `bool_val` (11). TF2 `tf.summary.scalar` writes a float32
scalar in `float_val`, not `tensor_content`. Both paths are decoded.

Kind resolution, in order: `simple_value` present → scalar. `histo` present →
histogram. `tensor` present: plugin `scalars` or rank-0 numeric → scalar;
plugin `histograms` or shape `[k,3]` float64 → histogram; plugin `text` or
dtype `DT_STRING` → text. Everything else is counted and ignored, and the
count is visible in the run's tooltip so nothing disappears silently.

Protobuf decoding is a 60-line hand-written reader over `DataView`: varint,
64-bit, length-delimited, 32-bit. Unknown fields are skipped by wire type.
No library, no schema compiler.

### Restart semantics

Trainers crash and resume from checkpoints. TensorBoard's rule, applied
globally per run, purges everything after a step regression and produces the
famous zigzag when it doesn't. BlernsBoard applies the rule per series: when a
point arrives with a step lower than or equal to the series' last step, all
existing points with step ≥ the new step are dropped. This means every scalar
series is strictly increasing in step, which makes binary search, nearest-step
lookup and per-pixel downsampling trivial. A setting `Keep overwritten points`
disables the purge and draws in arrival order (TensorBoard behaviour), for the
rare case where the regression is intentional.

Multiple event files inside one run directory (a new file per restart) are
read in filename order, which is timestamp order, and merged into the same
series under the same rule. Only the newest file is expected to grow. If an
older file changes after a newer one has been read (concurrent writers), the
merge order is no longer valid and the run is re-read from scratch; this is
verified by `tools/check_tail.mjs`, which reads 60% of every file, then the
rest, and checks the result equals a single full read, with and without
server-side Range support.

## 4. Feature inventory, with value assigned

Value is what a person training models gets out of the feature. Cost is code,
UI surface and risk. Kept features must earn their place.

| Feature | Value | Cost | Decision |
|---|---|---|---|
| Scalar line charts, grouped by tag prefix | core | med | keep |
| Every logged point kept, per-pixel min/max downsampling at draw time | high: TensorBoard reservoir-samples to 1000 points and loses spikes | med | keep |
| Debiased EMA smoothing with the raw line kept faint behind it | high, familiar | low | keep |
| X axis: step / relative time / wall clock | high | low | keep |
| Y axis: linear / log, global default plus per-chart override | high | low | keep |
| Robust Y fit (ignore outliers) | high: a single NaN-adjacent spike otherwise flattens the chart | low | keep, default on |
| Crosshair + one tooltip listing every visible run, sorted by value | core | med | keep |
| Linked crosshair across charts (same step highlighted everywhere) | med | low | keep |
| Drag to zoom X, double-click to reset; optional sync across charts | high | med | keep, sync off by default |
| Run list with colour, checkbox, regex filter, all/none/invert | core | low | keep |
| Hover a run name → highlight it in every chart | high | low | keep |
| Stable colour per run, chosen from a validated palette | high | low | keep |
| Pin charts to a top section | high for long sessions | low | keep |
| Expand a card to full width | med | low | keep |
| Download CSV of a chart's visible data | med | low | keep |
| State in URL hash, remembered per logdir in localStorage | high | low | keep |
| Auto refresh with visible "updated Ns ago" and interval control | core | low | keep |
| Per-run parse warnings surfaced in the UI | med, robustness | low | keep |
| Histograms as a step × value heatmap | med | med | keep, after scalars are solid |
| Text summaries with a step slider | med | low | keep |
| Images | med | med (memory) | v1.1, needs a keep-last-N cap |
| HParams table | med | high (own proto, own plugin schema) | defer |
| Light theme | low for this audience, but free with tokens | low | keep as toggle, dark default |
| Wheel zoom | negative: hijacks page scroll | low | cut |
| Per-chart legend boxes | negative at 30 charts: the sidebar is the legend | low | cut |
| Toast notifications | negative | low | cut |
| Tag search that hides groups instantly | high | low | keep |
| "Show data download links", "Horizontal axis: wall/relative" hidden in a settings gear | negative | | cut; controls live in the sidebar, always visible |

## 5. Layout

    ┌──────────────────────────────────────────────────────────────────────┐
    │ BlernsBoard  /logs/exp-42          ● updated 4s ago  15s ▾  ↻    ☾  │
    ├──────────────┬───────────────────────────────────────────────────────┤
    │ Runs     12  │ filter tags…                              [1][2][3] │
    │ filter…      │                                                      │
    │ all none inv │ ★ Pinned (2)                                         │
    │ ■ ☑ baseline │ ┌──────────────┐ ┌──────────────┐                    │
    │ ■ ☑ lr-3e-4  │ │ loss/train   │ │ eval/acc     │                    │
    │ ■ ☐ lr-1e-3 ⚠│ └──────────────┘ └──────────────┘                    │
    │ …            │                                                      │
    │              │ loss (3)                                             │
    │ Display      │ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │
    │ smoothing ─● │ │              │ │              │ │              │   │
    │ x: step      │ └──────────────┘ └──────────────┘ └──────────────┘   │
    │ y: linear    │                                                      │
    │ ☑ outliers   │ eval (2)                                             │
    │ ☐ sync zoom  │ …                                                    │
    └──────────────┴───────────────────────────────────────────────────────┘

- Header: identity, where we are, freshness, refresh controls, theme. Nothing
  else. The freshness dot is the only status indicator; it is grey while
  fetching, white when fresh, amber with text when the server is unreachable.
- Sidebar, 260px, scrolls independently. Runs first because they are the
  legend for every chart. Display settings below, always visible, no gear
  menu. On narrow screens the sidebar collapses to a top drawer.
- Main: one filter row, then groups. Group header is the prefix and a count,
  click to collapse. Grid columns are automatic from width (min card 340px),
  with a 1/2/3/4 override. Cards are a fixed 230px tall so refreshes never
  reflow.
- Card: title in secondary ink with the group prefix muted, action glyphs
  appear on hover (pin, expand, log y, CSV). Plot fills the rest. Y tick
  labels sit outside the plot on the left, in a margin sized to the widest
  label (labels drawn inside the plot collided with the first points of every
  series). No per-card legend.
- Sidebar width is draggable (180–600px) and remembered. Long run names keep
  their basename readable and truncate the directory part first, because in a
  sweep the basename is what differs.

Left aligned throughout. The chart grid is the memorable element; everything
around it is quiet.

## 6. Charts

### Colour

Colour is reserved for data. UI chrome is monochrome so a coloured pixel
always means a run. Ten run colours, generated in OKLCH at L≈0.665 and
validated with the dataviz palette checker against the card surface
(`#15161a`, dark mode): lightness band, chroma floor, adjacent-pair CVD ΔE
(worst 14.3 deutan), normal-vision ΔE (worst 23.6), 3:1 contrast. Order:

    #2a97f7 blue, #e86545 orange, #15a8ae teal, #d77804 amber, #947df3 violet,
    #70a71b lime, #d962ab pink, #b98c06 gold, #c06cd3 magenta, #03af73 green

Runs 11–20 reuse the hues at a lighter step; beyond that the cycle repeats.
Colour is assigned to a run once, in sorted order of the run name, and never
reassigned when runs are hidden or filtered (colour follows the entity). A
run's swatch can be clicked to advance to the next colour, persisted.

The raw line under a smoothed line is the same colour at 25% alpha. Hovering a
run in the sidebar or tooltip dims every other run to 20%.

### Scaling

- X domain: union of visible runs' visible data, or the zoom range.
- Y domain: when smoothing > 0, the extents of the smoothed lines (the raw
  noise is drawn but does not drive the scale). When smoothing is 0 and
  "ignore outliers" is on, the 1st–99th percentile of visible values. 6%
  padding. A constant series gets ±1 (or ±|v|/10) so it is still a line in the
  middle, not on the border.
- Log Y: non-positive values are skipped, and a footnote in the card says
  how many. If nothing positive remains the card falls back to linear and says
  so. Log ticks at decades with 2 and 5 minors when there are fewer than three
  decades.
- Ticks: a nice-number generator producing 3–6 Y ticks and 4–8 X ticks.
  Labels are formatted with the fewest digits that make adjacent ticks
  distinct (`0.1231`, `0.1232` rather than `0.12`, `0.12`). Steps are `12k`,
  `1.5M`. Relative time is `1h20m`. Wall time is `14:05` or `Sep 14` depending
  on span.
- Downsampling: for each pixel column in the visible range take the first,
  min, max and last value in that column and draw them in order. Spikes
  survive; the polyline is at most 4× width points. Smoothing is applied to the
  full-resolution series before downsampling so it is exactly the EMA
  TensorBoard shows.
- Rendering: one `<canvas>` per card at device pixel ratio, plus one shared
  overlay canvas for the crosshair so hover never redraws data. Cards outside
  the viewport are not drawn (IntersectionObserver). Downsampled arrays are
  cached per (series, width, smoothing, domain) and invalidated on append.

### Interaction

- Crosshair snaps to the nearest step of the nearest run, then the tooltip
  lists every visible run at that step: smoothed value strong, raw value
  muted, run name, colour stroke. Sorted by value so the tooltip reads like
  the chart. Step and time in the tooltip header. Positioned inside the card,
  flipping sides near the edge. Above 14 runs the tooltip shows the 14 around
  the nearest one and says how many more there are. The nearest run is also
  highlighted in the sidebar.
- Drag on the plot: a translucent X range appears; release to zoom. Double
  click resets. Escape resets. With "Sync zoom" on, the range applies to every
  chart on the same X axis.
- Keyboard: cards are focusable, left/right arrows step the crosshair through
  the drawn points, Escape resets zoom.

## 7. Visual tokens

    page          #101114     card          #15161a
    border        rgba(255,255,255,.08)
    ink           #e7e7e4     ink-2         #a3a49f     ink-3   #6c6d72
    grid          #23242a     axis          #34353b
    warn          #e0a23a     (status, with a glyph and text, never alone)
    font          system-ui sans, 13px UI, 11px ticks, tabular-nums for numbers
    radius        4px cards, 3px controls
    motion        none except a 120ms opacity fade on data arrival, disabled
                  under prefers-reduced-motion

Light theme swaps the surfaces and ink and steps the palette to
`#2a78d6 #e35a2a #0e9a9f #c26d00 #7a63e6 #5b8f0f #c94d97 #9d7a00 #a94fbd #0a9a62`.

## 8. State

    #runs=baseline,lr-3e-4   selected runs (all if absent)
    &tags=loss|eval          tag regex
    &s=0.6                   smoothing weight
    &x=step|rel|wall         x axis
    &y=lin|log               y default
    &o=1                     ignore outliers
    &pin=loss/train,eval/acc pinned tags
    &cols=3                  column override
    &r=15                    refresh seconds, 0 = off
    &logdir=…                root (only when not the page's directory)

Every change rewrites the hash (replaceState, no history spam) and mirrors to
`localStorage["blernsboard:" + root]`. On load, hash wins, then storage, then
defaults.

## 9. Performance budgets

- 100 runs × 50 tags × 100k points parses in a worker; the UI thread only
  receives typed-array deltas and never blocks on parsing.
- Full redraw of 40 visible cards × 10 runs under 16ms after the downsample
  cache is warm; under 200ms cold.
- Hover cost is one overlay clear and a few strokes, independent of data size.
- Memory: 24 bytes per scalar point (step, value, wall as float64). 10M points
  is 240MB, acceptable for a lab tool, and visible in the header tooltip.

## 10. Failure states

| Situation | What the person sees |
|---|---|
| Discovery of a deep tree | Directory visits hold a network slot only during the fetch, never while waiting on children (holding it deadlocked at 7+ open directories) |
| Root listing 404 / not HTML / CORS | One card: what was requested, what came back, the exact command to run |
| Listing OK, no tfevents anywhere | "No event files under `/logs/`. Looking for names containing `tfevents`." |
| Corrupt record | Run gets ⚠ with "CRC mismatch at byte 48,212 in events…1234" on hover; data before it is kept |
| Server unreachable during refresh | Freshness dot turns amber, "retrying", charts unchanged |
| A tag has no positive values under log Y | Card note "log axis unavailable, 0 positive values" and linear fallback |
| Regex filter invalid | Input outlined in warn colour, previous filter stays applied |
| Run selection hides every run | Grid shows "No runs selected" with a button to select all |

## 11. Anti-patterns deliberately avoided

Scroll hijacking (no wheel zoom). Hidden settings menus. Toasts. Layout shift
on refresh. Colour as the only identity (names in tooltip and sidebar). Icons
without labels (every glyph has `aria-label` and `title`). Reservoir sampling
that throws data away. A different rounding on each axis tick. Dual Y axes.
Spinners with no explanation. Empty states without a next action. A modal for
anything.

## 12. Testing

- `tools/make_demo_logs.py` writes a realistic logdir with the real
  `tensorboard` package: several runs, nested run dirs, TF1-style
  `simple_value` and TF2-style tensor scalars, histograms (both encodings),
  text, a restart with step regression, a file with a truncated tail, a file
  with a corrupted CRC, NaN and negative values for log scale.
- `tools/check_parser.mjs` runs the page's reader in Node against those files
  and checks counts and values against the Python writer's ground truth.
- Headless Chromium screenshots of the page served by `python3 -m http.server`
  for visual review in both themes at 1440 and 900 px widths.
