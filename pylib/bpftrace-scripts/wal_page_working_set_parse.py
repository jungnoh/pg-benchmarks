#!/usr/bin/env python3
"""wal_page_working_set_parse.py

Parses the output of wal_page_working_set.bt and computes the number of
distinct WAL pages loaded from disk within a rolling window of configurable
width.  Produces a text summary and a time-series graph.

The rolling-window distinct count answers:
  "How many unique WAL pages would I need to keep cached to avoid all
   re-reads within the last W seconds?"

Usage:
  ./wal_page_working_set_parse.py <logfile> [--windows 1,5,10,30] [-o out.png]

Output columns (text):
  time_ms  window_Xs_distinct_pages  ...
"""

import argparse
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

TAI_UTC_OFFSET_S = 37
PAGE_SIZE_KB = 4
DEFAULT_WINDOWS_S = [1, 5, 10, 30]


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


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_log(path):
    """Return (start_ns, events) where events is a list of (ts_ms, ino, page_idx)
    sorted by ts_ms."""
    start_ns = None
    events = []
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
            if parts[0] == "A" and len(parts) == 4:
                try:
                    events.append((int(parts[1]), int(parts[2]), int(parts[3])))
                except ValueError:
                    continue
    events.sort(key=lambda e: e[0])
    return start_ns, events


# ---------------------------------------------------------------------------
# Rolling-window distinct count
# ---------------------------------------------------------------------------


def rolling_distinct(events, window_ms, step_ms=500):
    """Compute the number of distinct (ino, page_idx) pairs accessed within
    the rolling window [t - window_ms, t] at every step_ms tick.

    Uses a deque + reference-count dict for O(N) total work.

    Returns a list of (tick_ms, distinct_count) pairs.
    """
    if not events:
        return []

    max_ts = events[-1][0]
    window = deque()  # (ts_ms, ino, page_idx)
    ref_count = defaultdict(int)  # (ino, page_idx) -> count in window
    distinct = 0

    result = []
    event_idx = 0
    n_events = len(events)

    for tick in range(0, max_ts + step_ms, step_ms):
        # Add events up to tick
        while event_idx < n_events and events[event_idx][0] <= tick:
            ts, ino, pidx = events[event_idx]
            key = (ino, pidx)
            if ref_count[key] == 0:
                distinct += 1
            ref_count[key] += 1
            window.append((ts, ino, pidx))
            event_idx += 1

        # Remove events older than the window
        cutoff = tick - window_ms
        while window and window[0][0] <= cutoff:
            _, ino, pidx = window.popleft()
            key = (ino, pidx)
            ref_count[key] -= 1
            if ref_count[key] == 0:
                del ref_count[key]
                distinct -= 1

        result.append((tick, distinct))

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def print_summary(window_series, windows_s):
    """Print peak and final distinct counts for each window size."""
    print(
        f"\n{'Window':>10}  {'Peak pages':>12}  {'Peak MB':>10}  {'Final pages':>12}  {'Final MB':>10}"
    )
    print("-" * 62)
    for w_s, series in zip(windows_s, window_series):
        if not series:
            continue
        counts = [c for _, c in series]
        peak = max(counts)
        final = counts[-1]
        print(
            f"{w_s:>9}s  {peak:>12,}  {peak * PAGE_SIZE_KB / 1024:>9.1f}M"
            f"  {final:>12,}  {final * PAGE_SIZE_KB / 1024:>9.1f}M"
        )
    print()


COLORS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#42d4f4"]


def build_figures(start_ns, windows_s, window_series, outpath):
    if start_ns is not None:
        start_dt = _tai_ns_to_utc(start_ns)
        print(f"Trace start (UTC): {start_dt:%Y-%m-%d %H:%M:%S}")
    else:
        print("Warning: no 'Start:' line found; using raw offsets.")
        start_dt = datetime(1970, 1, 1, tzinfo=timezone.utc)

    fig, (ax_pages, ax_mb) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

    for i, (w_s, series) in enumerate(zip(windows_s, window_series)):
        if not series:
            continue
        color = COLORS[i % len(COLORS)]
        ts_dt = _offset_to_datetime([r[0] for r in series], start_dt)
        counts = [r[1] for r in series]
        mb = [c * PAGE_SIZE_KB / 1024 for c in counts]
        label = f"{w_s}s window"
        ax_pages.plot(ts_dt, counts, linewidth=1.0, color=color, label=label)
        ax_mb.plot(ts_dt, mb, linewidth=1.0, color=color, label=label)

        peak_idx = int(max(range(len(counts)), key=lambda j: counts[j]))
        peak_ts = ts_dt[peak_idx]
        peak_cnt = counts[peak_idx]
        peak_mb = mb[peak_idx]

        for ax, peak_val, fmt in (
            (ax_pages, peak_cnt, f"{peak_cnt:,}"),
            (ax_mb, peak_mb, f"{peak_mb:.1f} MB"),
        ):
            ax.plot(peak_ts, peak_val, marker="v", markersize=7, color=color, zorder=5)
            ax.annotate(
                fmt,
                xy=(peak_ts, peak_val),
                xytext=(0, 8),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7,
                color=color,
                fontweight="bold",
            )

    ax_pages.set_ylabel("Distinct WAL pages (4 KB each)")
    ax_pages.set_title("Distinct WAL pages loaded in rolling window")
    ax_pages.legend(loc="upper left", fontsize=9)
    ax_pages.grid(True, alpha=0.3)
    _format_time_axis(ax_pages)

    ax_mb.set_ylabel("Distinct WAL pages (MB)")
    ax_mb.set_title("Same, in MB")
    ax_mb.legend(loc="upper left", fontsize=9)
    ax_mb.grid(True, alpha=0.3)
    _format_time_axis(ax_mb, is_bottom=True)

    fig.suptitle(
        f"WAL page working set — trace started {start_dt:%Y-%m-%d %H:%M:%S} UTC",
        fontsize=11,
        y=1.0,
    )
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    print(f"Saved to {outpath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Compute rolling-window distinct WAL page counts from "
        "wal_page_working_set.bt output"
    )
    parser.add_argument("logfile", help="Path to wal_page_working_set log file")
    parser.add_argument(
        "--windows",
        default=",".join(str(w) for w in DEFAULT_WINDOWS_S),
        help=f"Comma-separated rolling window widths in seconds "
        f"(default: {','.join(str(w) for w in DEFAULT_WINDOWS_S)})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="/tmp/wal_page_working_set.png",
        help="Output image path (default: /tmp/wal_page_working_set.png)",
    )
    args = parser.parse_args()

    windows_s = [int(w) for w in args.windows.split(",")]

    print(f"Parsing {args.logfile} ...")
    start_ns, events = parse_log(args.logfile)
    print(f"Parsed {len(events):,} page-load events.")

    if not events:
        print("No events found.")
        return

    window_series = []
    for w_s in windows_s:
        series = rolling_distinct(events, window_ms=w_s * 1000)
        window_series.append(series)
        print(f"  window={w_s}s: {len(series)} ticks computed")

    print_summary(window_series, windows_s)
    build_figures(start_ns, windows_s, window_series, args.output)


if __name__ == "__main__":
    main()
