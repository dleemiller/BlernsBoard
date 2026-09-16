#!/usr/bin/env python3
"""Write one demo run with histogram, text and scalar summaries using the real
`tensorboard` package, so the histogram heatmap can be seen on a real logdir.

Usage: make_hist_demo.py RUN_DIR      (created if missing; nothing else is touched)
"""
import math, os, sys, time
import numpy as np
from tensorboard.compat.proto import event_pb2, summary_pb2, histogram_pb2
from tensorboard.plugins.histogram import summary_v2 as hist_v2
from tensorboard.plugins.text import summary_v2 as text_v2
from tensorboard.summary.writer.record_writer import RecordWriter

run_dir = sys.argv[1]
os.makedirs(run_dir, exist_ok=True)
wall0 = time.time() - 6 * 3600
path = os.path.join(run_dir, f"events.out.tfevents.{int(wall0)}.demo.1.0")
f = open(path, "wb"); w = RecordWriter(f)
w.write(event_pb2.Event(wall_time=wall0, file_version="brain.Event:2").SerializeToString())
rng = np.random.default_rng(3)


def emit(step, summary, dt):
    ev = event_pb2.Event(wall_time=wall0 + step * dt, step=step); ev.summary.CopyFrom(summary)
    w.write(ev.SerializeToString())


def torch_style_hist(tag, data):
    """What torch.utils.tensorboard.add_histogram writes: HistogramProto with tensorflow-style bins."""
    counts, limits = np.histogram(data, bins=64)
    h = histogram_pb2.HistogramProto(min=float(data.min()), max=float(data.max()), num=float(data.size),
                                     sum=float(data.sum()), sum_squares=float((data ** 2).sum()))
    h.bucket_limit.extend(limits[1:].tolist()); h.bucket.extend(counts.tolist())
    s = summary_pb2.Summary(); s.value.add(tag=tag, histo=h); return s


steps = range(0, 40001, 500)
for step in steps:
    t = step / 40000
    # encoder weights: start near zero, spread out, develop a bimodal tail
    enc = np.concatenate([rng.normal(0, 0.02 + 0.3 * t, 6000), rng.normal(0.8 * t, 0.05, int(800 * t) + 1)])
    # gradient norms per layer: log-normal, shrinking as training settles, with an occasional spike
    grads = np.exp(rng.normal(math.log(1.0 - 0.7 * t + 0.05), 0.6, 4000)) * (4 if step in (8500, 21000) else 1)
    # attention entropy: moves from uniform-ish to peaked
    ent = np.clip(rng.normal(3.5 - 2.5 * t, 0.4 + 0.3 * (1 - t), 3000), 0, 4.2)
    emit(step, torch_style_hist("weights/encoder.layer3", enc), 0.5)          # TF1/PyTorch encoding
    emit(step, hist_v2.histogram_pb("grads/encoder", grads, buckets=40), 0.5)  # TF2 tensor encoding
    emit(step, torch_style_hist("attention/entropy", ent), 0.5)
    s = summary_pb2.Summary(); s.value.add(tag="loss/ctc", simple_value=float(2.4 * math.exp(-step / 12000) + 0.35 + rng.normal(0, 0.03)))
    s.value.add(tag="train/grad_norm", simple_value=float(np.percentile(grads, 90)))
    emit(step, s, 0.5)
    if step % 5000 == 0:
        emit(step, text_v2.text_pb("samples/greedy", f"step {step}: the quick brown fox jumps over the lazy dog\nref:  the quick brown fox jumps over the lazy dog\nhyp:  {'the quick brown fox jumps over the lazy dog' if t > 0.6 else 'the quik brown fox jumps over a lazy dog' if t > 0.2 else 'tha kwik bron fox jums over lazy dog'}"), 0.5)
w.close()
print(f"wrote {path} ({os.path.getsize(path) // 1024} kB, {len(steps)} steps)")
