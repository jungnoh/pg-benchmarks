#!/usr/bin/env python3
import argparse
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
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

# TAI is ahead of UTC by this many seconds (valid since 2017-01-01).
# Adjust if your kernel / leap-second table differs.
TAI_UTC_OFFSET_S = 37


def _tai_ns_to_utc(tai_ns):
    """Convert a TAI nanosecond timestamp to a UTC datetime."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return epoch + timedelta(seconds=(tai_ns / 1e9) - TAI_UTC_OFFSET_S)


def parse_log(path):
    start_ns = None
    stolen = []
    io_records = []
    miss_records = []
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue

            # "Start: <nanoseconds_tai>"  printed by BEGIN block
            if parts[0] == "Start:" and len(parts) == 2:
                try:
                    start_ns = int(parts[1])
                except ValueError:
                    pass
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
    return start_ns, stolen, io_records, miss_records


def _offset_to_datetime(offsets_ms, start_dt):
    """Convert a list of millisecond offsets to datetime objects."""
    return [start_dt + timedelta(milliseconds=ms) for ms in offsets_ms]


def _stacked_bar(ax, timestamps, vals, indices, labels, colors):
    """Draw a stacked bar chart for the given column indices."""
    if len(timestamps) > 1:
        diffs = mdates.date2num(timestamps)
        bar_width = np.median(np.diff(diffs)) * 0.9
    else:
        bar_width = 0.05 / 86400  # tiny fraction of a day
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


def _format_time_axis(ax, is_bottom=False):
    """Apply a human-readable time formatter to the x-axis."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    if is_bottom:
        ax.set_xlabel("Time (UTC)")
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(30)
        lbl.set_ha("right")


def build_figures(start_ns, stolen, io_records, miss_records, outpath):
    if start_ns is not None:
        start_dt = _tai_ns_to_utc(start_ns)
        print(f"Trace start (UTC): {start_dt:%Y-%m-%d %H:%M:%S}")
    else:
        # Fallback: no Start line found; treat offset 0 as epoch (old behaviour)
        print("Warning: no 'Start:' line found; using raw offsets as seconds.")
        start_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)

    ts_dt = _offset_to_datetime([r[0] for r in stolen], start_dt)
    rate = [r[1] * 20 for r in stolen]  # 50ms interval -> pages/sec
    cumulative = [r[2] for r in stolen]

    fig, axes = plt.subplots(6, 1, figsize=(14, 24))
    ax_rate, ax_cum, ax_miss_bg, ax_miss_other, ax_io_bg, ax_io_other = axes

    bg_indices = list(range(5))  # 0..4: known background processes

    # --- Reclaim rate ---
    ax_rate.fill_between(ts_dt, rate, alpha=0.4)
    ax_rate.plot(ts_dt, rate, linewidth=0.8)
    ax_rate.set_ylabel("Reclaim rate (pages/sec)")
    ax_rate.set_title("pgsteal_file reclaim rate")
    ax_rate.grid(True, alpha=0.3)
    _format_time_axis(ax_rate)

    # --- Cumulative reclaimed ---
    ax_cum.plot(ts_dt, cumulative, linewidth=1.0, color="tab:orange")
    ax_cum.set_ylabel("Cumulative pages reclaimed")
    ax_cum.set_title("Cumulative pgsteal_file")
    ax_cum.grid(True, alpha=0.3)
    _format_time_axis(ax_cum)

    # --- Cache misses: background processes ---
    if miss_records:
        m_dt = _offset_to_datetime([r[0] for r in miss_records], start_dt)
        m_vals = np.array([r[1] for r in miss_records])  # shape (N, 6)
        _stacked_bar(ax_miss_bg, m_dt, m_vals, bg_indices, PROC_LABELS, PROC_COLORS)
    ax_miss_bg.set_ylabel("Cache misses (per interval)")
    ax_miss_bg.set_title("Cache misses — background processes")
    ax_miss_bg.grid(True, alpha=0.3, axis="y")
    ax_miss_bg.legend(loc="upper right", fontsize=8, ncol=3)
    _format_time_axis(ax_miss_bg)

    # --- Cache misses: other (client backends etc.) ---
    if miss_records:
        ax_miss_other.fill_between(m_dt, m_vals[:, 5], alpha=0.4, color=PROC_COLORS[5])
        ax_miss_other.plot(
            m_dt,
            m_vals[:, 5],
            linewidth=0.8,
            color=PROC_COLORS[5],
            label=PROC_LABELS[5],
        )
    ax_miss_other.set_ylabel("Cache misses (per interval)")
    ax_miss_other.set_title("Cache misses — other (client backends, etc.)")
    ax_miss_other.grid(True, alpha=0.3, axis="y")
    ax_miss_other.legend(loc="upper right", fontsize=8)
    _format_time_axis(ax_miss_other)

    # --- IO commands: background processes ---
    if io_records:
        i_dt = _offset_to_datetime([r[0] for r in io_records], start_dt)
        i_vals = np.array([r[1] for r in io_records])  # shape (N, 6)
        _stacked_bar(ax_io_bg, i_dt, i_vals, bg_indices, PROC_LABELS, PROC_COLORS)
        bg_totals = i_vals[:, bg_indices].sum(axis=1)
        ax_io_bg.set_ylim(0, bg_totals.max() * 1.1 if bg_totals.max() > 0 else 1)
    ax_io_bg.set_ylabel("IO commands (per interval)")
    ax_io_bg.set_title("IO commands — background processes")
    ax_io_bg.grid(True, alpha=0.3, axis="y")
    ax_io_bg.legend(loc="upper right", fontsize=8, ncol=3)
    _format_time_axis(ax_io_bg)

    # --- IO commands: other (client backends etc.) ---
    if io_records:
        ax_io_other.fill_between(i_dt, i_vals[:, 5], alpha=0.4, color=PROC_COLORS[5])
        ax_io_other.plot(
            i_dt,
            i_vals[:, 5],
            linewidth=0.8,
            color=PROC_COLORS[5],
            label=PROC_LABELS[5],
        )
    ax_io_other.set_ylabel("IO commands (per interval)")
    ax_io_other.set_title("IO commands — other (client backends, etc.)")
    ax_io_other.grid(True, alpha=0.3, axis="y")
    ax_io_other.legend(loc="upper right", fontsize=8)
    _format_time_axis(ax_io_other, is_bottom=True)

    fig.suptitle(
        f"Trace started {start_dt:%Y-%m-%d %H:%M:%S} UTC",
        fontsize=11,
        y=1.0,
    )
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
    start_ns, stolen, io_records, miss_records = parse_log(args.logfile)
    print(
        f"Parsed {len(stolen)} stolen, {len(io_records)} IO, {len(miss_records)} miss samples."
    )
    build_figures(start_ns, stolen, io_records, miss_records, args.output)


if __name__ == "__main__":
    main()
