#!/usr/bin/env python3
"""Write a realistic demo logdir with the real `tensorboard` package.

Covers every encoding BlernsBoard must read:
  - TF1-style scalars (Summary.Value.simple_value)          run: baseline, wd-0.1
  - TF2-style scalars (TensorProto float_val + plugin data) run: tf2-style
  - histograms, both HistogramProto and [k,3] tensor        run: baseline, tf2-style
  - text summaries                                          run: baseline
  - a restart with step regression across two files         run: restart
  - a truncated trailing record                             run: truncated
  - a corrupted CRC mid-file                                run: corrupt
  - NaN, inf, negative and zero values                      run: weird
  - nested run directories                                  run: sweep/lr-1e-3, sweep/lr-3e-4
  - a large run with 50k points per tag                     run: big

Ground truth is written to <out>/_truth.json for tools/check_parser.mjs.
Usage: make_demo_logs.py OUT_DIR
"""
import json, math, os, random, shutil, struct, sys, time

import numpy as np
from tensorboard.compat.proto import event_pb2, summary_pb2, histogram_pb2
from tensorboard.compat.proto.summary_pb2 import SummaryMetadata
from tensorboard.plugins.scalar import summary_v2 as scalar_v2
from tensorboard.plugins.histogram import summary_v2 as hist_v2
from tensorboard.plugins.text import summary_v2 as text_v2
from tensorboard.summary.writer.record_writer import RecordWriter

out = sys.argv[1] if len(sys.argv) > 1 else "demo_logs"
if os.path.exists(out):
    shutil.rmtree(out)
os.makedirs(out)
truth = {}
random.seed(7)
np.random.seed(7)
T0 = 1_700_000_000.0


class Writer:
    def __init__(self, run, wall0, host="demo", pid=1):
        d = os.path.join(out, run)
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, f"events.out.tfevents.{int(wall0)}.{host}.{pid}.0")
        self.f = open(self.path, "wb")
        self.w = RecordWriter(self.f)
        self.run = run
        ev = event_pb2.Event(wall_time=wall0, file_version="brain.Event:2")
        self.w.write(ev.SerializeToString())
        self.wall = wall0

    def event(self, step, summary=None, session_log=None, dt=1.0):
        self.wall += dt
        ev = event_pb2.Event(wall_time=self.wall, step=step)
        if summary is not None:
            ev.summary.CopyFrom(summary)
        if session_log is not None:
            ev.session_log.CopyFrom(session_log)
        self.w.write(ev.SerializeToString())

    def scalar_v1(self, step, tag, value, dt=1.0):
        s = summary_pb2.Summary()
        v = s.value.add(tag=tag, simple_value=float(value))
        v.metadata.plugin_data.plugin_name = "scalars"
        self.event(step, s, dt=dt)
        record(self.run, tag, step, value, self.wall)

    def scalar_v2(self, step, tag, value, dt=1.0):
        s = scalar_v2.scalar_pb(tag, np.float32(value))
        self.event(step, s, dt=dt)
        record(self.run, tag, step, float(np.float32(value)), self.wall)

    def hist_v1(self, step, tag, data):
        h = histogram_pb2.HistogramProto()
        data = np.asarray(data, dtype=np.float64)
        h.min, h.max, h.num = float(data.min()), float(data.max()), float(data.size)
        h.sum, h.sum_squares = float(data.sum()), float((data ** 2).sum())
        # TF-style exponential bucket limits
        limits = []
        v = 1e-12
        while v < 1e3:
            limits.append(v)
            v *= 1.1
        limits = sorted(set([-x for x in limits] + [0.0] + limits))
        counts = np.histogram(data, bins=[-np.inf] + limits + [np.inf])[0]
        h.bucket_limit.extend(limits + [np.inf])
        h.bucket.extend(counts.tolist())
        s = summary_pb2.Summary()
        s.value.add(tag=tag, histo=h)
        self.event(step, s)

    def hist_v2(self, step, tag, data):
        self.event(step, hist_v2.histogram_pb(tag, np.asarray(data), buckets=30))

    def text(self, step, tag, text):
        self.event(step, text_v2.text_pb(tag, text))

    def close(self):
        self.w.close()


def record(run, tag, step, value, wall):
    """Ground truth with BlernsBoard's purge rule: step >= new step is dropped."""
    series = truth.setdefault(run, {}).setdefault(tag, [])
    while series and series[-1][0] >= step:
        series.pop()
    series.append([step, value, wall])


def curve(step, kind, noise=0.05, seed=0):
    r = random.Random(seed * 100003 + step)
    if kind == "loss":
        return 2.5 * math.exp(-step / 3000) + 0.3 + r.gauss(0, noise)
    if kind == "acc":
        return 1 - 0.9 * math.exp(-step / 2500) + r.gauss(0, noise / 3)
    if kind == "lr":
        return 3e-4 * (step / 500 if step < 500 else 0.5 * (1 + math.cos(math.pi * (step - 500) / 9500)))
    if kind == "gn":
        return abs(r.gauss(1.0, 0.3)) * (5 if r.random() < 0.003 else 1)
    return r.random()


def standard_run(name, seed, v2=False, steps=10000, every=10, eval_every=500, wd=0.0):
    w = Writer(name, T0 + seed * 3600)
    sc = w.scalar_v2 if v2 else w.scalar_v1
    for step in range(0, steps + 1, every):
        sc(step, "loss/train", curve(step, "loss", seed=seed) + wd, dt=0.7)
        sc(step, "train/lr", curve(step, "lr", seed=seed), dt=0)
        sc(step, "train/grad_norm", curve(step, "gn", seed=seed), dt=0)
        if step % eval_every == 0:
            sc(step, "loss/eval", curve(step, "loss", noise=0.02, seed=seed + 1) + wd + 0.1, dt=0)
            sc(step, "eval/accuracy", curve(step, "acc", seed=seed) - wd, dt=0)
            sc(step, "eval/wer", 0.5 * (1 - curve(step, "acc", seed=seed)) + wd, dt=0)
    return w


# --- baseline: v1 scalars, v1 histograms, text -------------------------------
w = standard_run("baseline", seed=1)
for step in range(0, 10001, 1000):
    w.hist_v1(step, "weights/layer1", np.random.randn(2000) * (1 + step / 10000) + step / 20000)
    w.text(step, "samples/decoded", f"step {step}: the quick brown fox jumps over the lazy dog ({step // 1000})")
w.close()

# --- wd-0.1: v1 scalars, different seed ---------------------------------------
standard_run("wd-0.1", seed=2, wd=0.1).close()

# --- tf2-style: tensor scalars, v2 histograms ---------------------------------
w = standard_run("tf2-style", seed=3, v2=True)
for step in range(0, 10001, 1000):
    w.hist_v2(step, "weights/layer1", np.random.randn(2000) * 0.5 + math.sin(step / 2000))
w.close()

# --- sweep/*: nested run directories ------------------------------------------
standard_run("sweep/lr-1e-3", seed=4, steps=6000).close()
standard_run("sweep/lr-3e-4", seed=5, steps=8000).close()

# --- restart: two files, second resumes from step 4000 ------------------------
w = Writer("restart", T0 + 10 * 3600, pid=10)
for step in range(0, 6001, 10):
    w.scalar_v1(step, "loss/train", curve(step, "loss", seed=6), dt=0.7)
w.close()
w = Writer("restart", T0 + 10 * 3600 + 5000, pid=11)
w.event(4000, session_log=event_pb2.SessionLog(status=event_pb2.SessionLog.START))
for step in range(4000, 9001, 10):
    w.scalar_v1(step, "loss/train", curve(step, "loss", seed=6) + 0.2, dt=0.7)
w.close()

# --- truncated: valid file cut mid-record -------------------------------------
w = Writer("truncated", T0 + 11 * 3600)
for step in range(0, 2001, 10):
    w.scalar_v1(step, "loss/train", curve(step, "loss", seed=7))
w.close()
with open(w.path, "r+b") as f:
    f.truncate(os.path.getsize(w.path) - 7)
truth["truncated"]["loss/train"].pop()  # last record is gone

# --- corrupt: flip a byte in the middle -------------------------------------
w = Writer("corrupt", T0 + 12 * 3600)
for step in range(0, 2001, 10):
    w.scalar_v1(step, "loss/train", curve(step, "loss", seed=8))
w.close()
size = os.path.getsize(w.path)
with open(w.path, "r+b") as f:
    f.seek(size // 2)
    b = f.read(1)
    f.seek(size // 2)
    f.write(bytes([b[0] ^ 0xFF]))
truth["corrupt"]["_note"] = "parser must stop at first CRC failure; count must be < %d" % len(truth["corrupt"]["loss/train"])

# --- weird: NaN, inf, negatives, zeros, constant, single point ----------------
w = Writer("weird", T0 + 13 * 3600)
for step in range(0, 1001, 10):
    v = math.sin(step / 100)
    w.scalar_v1(step, "weird/signed", v)
    w.scalar_v1(step, "weird/with_nan", float("nan") if step % 200 == 0 else v + 1.5)
    w.scalar_v1(step, "weird/with_inf", float("inf") if step == 500 else v + 1.5)
    w.scalar_v1(step, "weird/constant", 3.0)
    w.scalar_v1(step, "weird/tiny", 1e-7 * (1 + v))
    w.scalar_v1(step, "weird/huge", 1e9 * (2 + v))
w.scalar_v1(0, "weird/single_point", 42.0)
w.close()

# --- big: 50k points per tag ---------------------------------------------------
w = Writer("big", T0 + 14 * 3600)
for step in range(0, 50000):
    w.scalar_v1(step, "loss/train", curve(step, "loss", noise=0.15, seed=9), dt=0.05)
    w.scalar_v1(step, "train/grad_norm", curve(step, "gn", seed=9), dt=0)
w.close()

# --- not a run: a directory with only checkpoints -----------------------------
os.makedirs(os.path.join(out, "checkpoints"), exist_ok=True)
with open(os.path.join(out, "checkpoints", "model-1000.pt"), "wb") as f:
    f.write(os.urandom(4096))

with open(os.path.join(out, "_truth.json"), "w") as f:
    json.dump(truth, f)
n = sum(len(v) for r in truth.values() for k, v in r.items() if isinstance(v, list))
print(f"wrote {out}: {len(truth)} runs, {n} scalar points")
