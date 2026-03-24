#!/usr/bin/env python3
"""wal_cache_pages_graph.py

Parses the output of wal_cache_pages.bt and produces a 3-panel time-series graph:
  1. WAL pages currently resident in the OS page cache
  2. WAL page add and evict rates per 500 ms interval
  3. Net page flow per interval (adds - evicts)

Usage:
  ./wal_cache_pages_graph.py <logfile> [-o output.png]
"""

import argparse
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

# TAI is ahead of UTC by 37 seconds (valid since 2017-01-01).
TAI_UTC_OFFSET_S = 37
PAGE_SIZE_KB = 4


def _tai_ns_to_utc(tai_ns):
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return epoch + timedelta(seconds=(tai_ns / 1e9) - TAI_UTC_OFFSET_S)


def _offset_to_datetime(offsets_ms, start_dt):
    return [start_dt + timedelta(milliseconds=ms) for ms in offsets_ms]


def _format_time_axis(ax, is_bottom=False):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    if is_bottom:
        ax.set_xlabel("Time (UTC)")
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(30)
        lbl.set_ha("right")


def parse_log(path):
    start_ns = None
    records = []  # (ts_ms, wal_active, interval_adds, interval_evicts)
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "Start:" and len(parts) == 2:
                try:
                    start_ns = int(parts[1])
                except ValueError:
                    pass
                continue
            if parts[0] == "W" and len(parts) == 5:
                try:
                    records.append(
                        (
                            int(parts[1]),
                            int(parts[2]),
                            int(parts[3]),
                            int(parts[4]),
                        )
                    )
                except ValueError:
                    continue
    return start_ns, records


def build_figures(start_ns, records, outpath):
    if not records:
        print("No WAL page records found in log.")
        return

    if start_ns is not None:
        start_dt = _tai_ns_to_utc(start_ns)
        print(f"Trace start (UTC): {start_dt:%Y-%m-%d %H:%M:%S}")
    else:
        print("Warning: no 'Start:' line found; using raw offsets as seconds.")
        start_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)

    ts_ms = [r[0] for r in records]
    active = np.array([r[1] for r in records])
    adds = np.array([r[2] for r in records])
    evicts = np.array([r[3] for r in records])
    net = adds - evicts

    ts_dt = _offset_to_datetime(ts_ms, start_dt)

    # Convert pages → MB for the active count axis
    active_mb = active * PAGE_SIZE_KB / 1024

    print(f"Samples        : {len(records)}")
    print(
        f"Peak active    : {active.max()} pages ({active.max() * PAGE_SIZE_KB / 1024:.1f} MB)"
    )
    print(
        f"Final active   : {active[-1]} pages ({active[-1] * PAGE_SIZE_KB / 1024:.1f} MB)"
    )
    print(
        f"Total adds     : {adds.sum()} pages ({adds.sum() * PAGE_SIZE_KB / 1024:.1f} MB)"
    )
    print(
        f"Total evicts   : {evicts.sum()} pages ({evicts.sum() * PAGE_SIZE_KB / 1024:.1f} MB)"
    )

    fig, (ax_active, ax_rate, ax_net) = plt.subplots(3, 1, figsize=(14, 12))

    # ── Panel 1: Active WAL pages ──────────────────────────────────────────────
    ax_active.fill_between(ts_dt, active_mb, alpha=0.3, color="tab:blue")
    ax_active.plot(ts_dt, active_mb, linewidth=0.9, color="tab:blue")
    ax_active.set_ylabel("WAL pages in cache (MB)")
    ax_active.set_title("Active WAL file pages in OS page cache")
    ax_active.grid(True, alpha=0.3)
    _format_time_axis(ax_active)

    # Add a secondary y-axis in pages
    ax_active2 = ax_active.twinx()
    ax_active2.set_ylim(
        ax_active.get_ylim()[0] * 1024 / PAGE_SIZE_KB,
        ax_active.get_ylim()[1] * 1024 / PAGE_SIZE_KB,
    )
    ax_active2.set_ylabel("pages (4 KB each)")

    # ── Panel 2: Add / evict rates ────────────────────────────────────────────
    if len(ts_dt) > 1:
        diffs = mdates.date2num(ts_dt)
        bar_width = np.median(np.diff(diffs)) * 0.85
    else:
        bar_width = 0.05 / 86400

    ax_rate.bar(
        ts_dt,
        adds,
        width=bar_width,
        color="tab:green",
        alpha=0.7,
        label="adds (pages loaded)",
    )
    ax_rate.bar(
        ts_dt,
        evicts,
        width=bar_width,
        color="tab:red",
        alpha=0.7,
        label="evicts (pages removed)",
        bottom=0,
    )
    ax_rate.set_ylabel("Pages per 500 ms interval")
    ax_rate.set_title("WAL page cache load / evict rate")
    ax_rate.grid(True, alpha=0.3, axis="y")
    ax_rate.legend(loc="upper right", fontsize=9)
    _format_time_axis(ax_rate)

    # ── Panel 3: Net flow ─────────────────────────────────────────────────────
    colors = np.where(net >= 0, "tab:green", "tab:red")
    ax_net.bar(ts_dt, net, width=bar_width, color=colors, alpha=0.7)
    ax_net.axhline(0, color="black", linewidth=0.6, linestyle="--")
    ax_net.set_ylabel("Net pages per 500 ms interval")
    ax_net.set_title("Net WAL page cache flow (adds − evicts)")
    ax_net.grid(True, alpha=0.3, axis="y")
    _format_time_axis(ax_net, is_bottom=True)

    fig.suptitle(
        f"WAL page cache occupancy — trace started {start_dt:%Y-%m-%d %H:%M:%S} UTC",
        fontsize=11,
        y=1.0,
    )
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    print(f"Saved to {outpath}")


def main():
    parser = argparse.ArgumentParser(
        description="Plot WAL page cache occupancy from wal_cache_pages.bt output"
    )
    parser.add_argument("logfile", help="Path to the wal_cache_pages log file")
    parser.add_argument(
        "-o",
        "--output",
        default="/tmp/wal_cache_pages.png",
        help="Output image path (default: /tmp/wal_cache_pages.png)",
    )
    args = parser.parse_args()
    print(f"Parsing {args.logfile} ...")
    start_ns, records = parse_log(args.logfile)
    print(f"Parsed {len(records)} samples.")
    build_figures(start_ns, records, args.output)


if __name__ == "__main__":
    main()
