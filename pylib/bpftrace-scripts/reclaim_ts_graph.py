#!/usr/bin/env python3
import argparse

import matplotlib.pyplot as plt
import numpy as np

PROC_LABELS = [
    "io worker",
    "checkpointer",
    "walwriter",
    "autovacuum",
    "bg writer",
    "other",
]
PROC_COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4"]


def parse_log(path):
    stolen = []
    io_records = []
    miss_records = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            tag = parts[0]
            if tag == "S" and len(parts) == 4:
                try:
                    ts_ms, delta, cumulative = (
                        int(parts[1]),
                        int(parts[2]),
                        int(parts[3]),
                    )
                    stolen.append((ts_ms, delta, cumulative))
                except ValueError:
                    continue
            elif tag == "I" and len(parts) == 8:
                try:
                    ts_ms = int(parts[1])
                    vals = [int(v) for v in parts[2:8]]
                    io_records.append((ts_ms, vals))
                except ValueError:
                    continue
            elif tag == "M" and len(parts) == 8:
                try:
                    ts_ms = int(parts[1])
                    vals = [int(v) for v in parts[2:8]]
                    miss_records.append((ts_ms, vals))
                except ValueError:
                    continue
    return stolen, io_records, miss_records


def _stacked_bar(ax, timestamps, vals, indices, labels, colors):
    """Draw a stacked bar chart for the given column indices."""
    bar_width = np.median(np.diff(timestamps)) * 0.9 if len(timestamps) > 1 else 0.05
    bottom = np.zeros(len(timestamps))
    for i in indices:
        col = vals[:, i]
        ax.bar(
            timestamps,
            col,
            width=bar_width,
            bottom=bottom,
            color=colors[i],
            label=labels[i],
            linewidth=0,
        )
        bottom += col


def build_figures(stolen, io_records, miss_records, outpath):
    ts = [r[0] / 1000.0 for r in stolen]
    rate = [r[1] * 20 for r in stolen]  # 50ms interval -> pages/sec
    cumulative = [r[2] for r in stolen]

    fig, axes = plt.subplots(6, 1, figsize=(14, 24), sharex=True)
    ax_rate, ax_cum, ax_miss_bg, ax_miss_other, ax_io_bg, ax_io_other = axes

    bg_indices = list(range(5))  # 0..4: known background processes

    # --- Reclaim rate ---
    ax_rate.fill_between(ts, rate, alpha=0.4)
    ax_rate.plot(ts, rate, linewidth=0.8)
    ax_rate.set_ylabel("Reclaim rate (pages/sec)")
    ax_rate.set_title("pgsteal_file reclaim rate")
    ax_rate.grid(True, alpha=0.3)

    # --- Cumulative reclaimed ---
    ax_cum.plot(ts, cumulative, linewidth=1.0, color="tab:orange")
    ax_cum.set_ylabel("Cumulative pages reclaimed")
    ax_cum.set_title("Cumulative pgsteal_file")
    ax_cum.grid(True, alpha=0.3)

    # --- Cache misses: background processes ---
    if miss_records:
        m_ts = [r[0] / 1000.0 for r in miss_records]
        m_vals = np.array([r[1] for r in miss_records])  # shape (N, 6)
        _stacked_bar(ax_miss_bg, m_ts, m_vals, bg_indices, PROC_LABELS, PROC_COLORS)
    ax_miss_bg.set_ylabel("Cache misses (per interval)")
    ax_miss_bg.set_title("Cache misses — background processes")
    ax_miss_bg.grid(True, alpha=0.3, axis="y")
    ax_miss_bg.legend(loc="upper right", fontsize=8, ncol=3)

    # --- Cache misses: other (client backends etc.) ---
    if miss_records:
        ax_miss_other.fill_between(m_ts, m_vals[:, 5], alpha=0.4, color=PROC_COLORS[5])
        ax_miss_other.plot(
            m_ts,
            m_vals[:, 5],
            linewidth=0.8,
            color=PROC_COLORS[5],
            label=PROC_LABELS[5],
        )
    ax_miss_other.set_ylabel("Cache misses (per interval)")
    ax_miss_other.set_title("Cache misses — other (client backends, etc.)")
    ax_miss_other.grid(True, alpha=0.3, axis="y")
    ax_miss_other.legend(loc="upper right", fontsize=8)

    # --- IO commands: background processes ---
    if io_records:
        i_ts = [r[0] / 1000.0 for r in io_records]
        i_vals = np.array([r[1] for r in io_records])  # shape (N, 6)
        _stacked_bar(ax_io_bg, i_ts, i_vals, bg_indices, PROC_LABELS, PROC_COLORS)
        bg_totals = i_vals[:, bg_indices].sum(axis=1)
        ax_io_bg.set_ylim(0, bg_totals.max() * 1.1 if bg_totals.max() > 0 else 1)
    ax_io_bg.set_ylabel("IO commands (per interval)")
    ax_io_bg.set_title("IO commands — background processes")
    ax_io_bg.grid(True, alpha=0.3, axis="y")
    ax_io_bg.legend(loc="upper right", fontsize=8, ncol=3)

    # --- IO commands: other (client backends etc.) ---
    if io_records:
        ax_io_other.fill_between(i_ts, i_vals[:, 5], alpha=0.4, color=PROC_COLORS[5])
        ax_io_other.plot(
            i_ts,
            i_vals[:, 5],
            linewidth=0.8,
            color=PROC_COLORS[5],
            label=PROC_LABELS[5],
        )
    ax_io_other.set_ylabel("IO commands (per interval)")
    ax_io_other.set_xlabel("Time (seconds)")
    ax_io_other.set_title("IO commands — other (client backends, etc.)")
    ax_io_other.grid(True, alpha=0.3, axis="y")
    ax_io_other.legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    print(f"Saved to {outpath}")


def main():
    parser = argparse.ArgumentParser(
        description="Visualize reclaim_ts reclaim patterns from bpftrace logs"
    )
    parser.add_argument("logfile", help="Path to the reclaim ts log file")
    parser.add_argument(
        "-o",
        "--output",
        default="/tmp/reclaim_ts.png",
        help="Output image path (default: /tmp/reclaim_ts.png)",
    )
    args = parser.parse_args()
    print(f"Parsing {args.logfile} ...")
    stolen, io_records, miss_records = parse_log(args.logfile)
    print(
        f"Parsed {len(stolen)} stolen, {len(io_records)} IO, {len(miss_records)} miss samples."
    )
    build_figures(stolen, io_records, miss_records, args.output)


if __name__ == "__main__":
    main()
