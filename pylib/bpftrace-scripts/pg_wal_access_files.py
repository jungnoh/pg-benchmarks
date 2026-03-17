#!/usr/bin/env python3
import argparse
import re
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

READ_COLOR = "#4C9BE8"
WRITE_COLOR = "#E8694C"
EVENT_RE = re.compile(r"^([RW])/(\d+)/([^/]+)/(-?\d+)/(-?\d+)$")


def parse_log(path):
    ops = []
    with open(path) as f:
        for line in f:
            m = EVENT_RE.match(line.strip())
            if m and int(m.group(5)) > 0:
                op, ts, fname, pos, size = m.groups()
                ops.append((op, int(ts), fname, int(pos), int(size)))
    return ops


def human_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def build_figures(ops, output_path):
    by_file = defaultdict(list)
    for op, ts, fname, pos, size in ops:
        by_file[fname].append((op, ts, size))

    ordered = sorted(by_file, key=lambda f: min(ts for _, ts, _ in by_file[f]))

    n = len(ordered)
    cols = min(3, n)
    rows = (n + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5, rows * 3), squeeze=False)
    fig.suptitle(
        "WAL File Access Patterns (ordered by first access)", fontsize=11, y=1.01
    )

    for idx, fname in enumerate(ordered):
        ax = axes[idx // cols][idx % cols]
        events = by_file[fname]
        reads = [(ts / 1e9, sz) for op, ts, sz in events if op == "R"]
        writes = [(ts / 1e9, sz) for op, ts, sz in events if op == "W"]

        all_file_ts = [ts / 1e9 for _, ts, _ in events]
        fspan = max(all_file_ts) - min(all_file_ts) or 1.0
        bar_w = fspan / max(len(events) * 2, 1)
        pad = fspan * 0.05

        for pts, color in [(reads, READ_COLOR), (writes, WRITE_COLOR)]:
            if pts:
                xs, ys = zip(*pts)
                ax.bar(xs, ys, width=bar_w, color=color, alpha=0.7, linewidth=0)

        ax.set_xlim(min(all_file_ts) - pad, max(all_file_ts) + pad)
        ax.set_ylim(0, max(sz for _, _, sz in events) * 1.15)
        ax.set_title(fname, fontsize=8, pad=3)
        ax.set_ylabel("Size", fontsize=7)
        yticks = [t for t in ax.get_yticks() if t >= 0]
        ax.set_yticks(yticks)
        ax.set_yticklabels([human_bytes(t) for t in yticks], fontsize=6)
        ax.tick_params(axis="x", labelsize=6)
        ax.grid(axis="y", linestyle="--", linewidth=0.4, alpha=0.5)
        if idx // cols == rows - 1 or idx + cols >= n:
            ax.set_xlabel("Time (s)", fontsize=7)

    for idx in range(n, rows * cols):
        axes[idx // cols][idx % cols].set_visible(False)

    fig.legend(
        handles=[
            mpatches.Patch(color=READ_COLOR, label="Read"),
            mpatches.Patch(color=WRITE_COLOR, label="Write"),
        ],
        loc="upper right",
        fontsize=8,
        framealpha=0.8,
    )

    plt.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"Saved → {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Visualize PostgreSQL WAL I/O patterns from bpftrace logs"
    )
    parser.add_argument("logfile", help="Path to the bpftrace WAL access log file")
    args = parser.parse_args()

    print(f"Parsing {args.logfile} ...")
    ops = parse_log(args.logfile)
    print(f"Parsed {len(ops)} I/O operations.")
    build_figures(ops, "/tmp/pg_wal_access_files.png")


if __name__ == "__main__":
    main()
