#!/usr/bin/env python3
import argparse
import re
from collections import defaultdict

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


def file_ranges(ops):
    spans = defaultdict(lambda: [float("inf"), float("-inf")])
    for _, ts, fname, _, _ in ops:
        spans[fname][0] = min(spans[fname][0], ts)
        spans[fname][1] = max(spans[fname][1], ts)
    return {f: (lo, hi) for f, (lo, hi) in spans.items()}


def find_max_overlap(ranges):
    events = []
    for fname, (lo, hi) in ranges.items():
        events.append((lo, +1, fname))
        events.append((hi, -1, fname))
    events.sort(key=lambda e: (e[0], e[1]))

    active, best_count, best_files = set(), 0, set()
    for ts, kind, fname in events:
        if kind == +1:
            active.add(fname)
        else:
            active.discard(fname)
        if len(active) > best_count:
            best_count = len(active)
            best_files = set(active)

    # find the contiguous window where best_count files overlap simultaneously
    starts = {f: ranges[f][0] for f in best_files}
    ends = {f: ranges[f][1] for f in best_files}
    window_start = max(starts.values())
    window_end = min(ends.values())

    return best_count, window_start, window_end, sorted(best_files)


def ns_to_s(ns):
    return ns / 1e9


def main():
    parser = argparse.ArgumentParser(
        description="Print overlapping WAL file access time ranges from bpftrace logs"
    )
    parser.add_argument("logfile", help="Path to the bpftrace WAL access log file")
    args = parser.parse_args()

    print(f"Parsing {args.logfile} ...")
    ops = parse_log(args.logfile)
    print(f"Parsed {len(ops)} I/O operations.\n")

    ranges = file_ranges(ops)

    print("Per-file access ranges (seconds from trace start):")
    for fname in sorted(ranges, key=lambda f: ranges[f][0]):
        lo, hi = ranges[fname]
        print(
            f"  {fname}  [{ns_to_s(lo):.3f}s, {ns_to_s(hi):.3f}s]  duration={ns_to_s(hi - lo):.3f}s"
        )

    count, win_start, win_end, files = find_max_overlap(ranges)

    print(f"\nMaximum simultaneous overlap: {count} file(s)")
    print(
        f"Overlap window: [{ns_to_s(win_start):.3f}s, {ns_to_s(win_end):.3f}s]  duration={ns_to_s(win_end - win_start):.3f}s"
    )
    print("Files active during this window:")
    for f in files:
        lo, hi = ranges[f]
        print(f"  {f}  [{ns_to_s(lo):.3f}s, {ns_to_s(hi):.3f}s]")


if __name__ == "__main__":
    main()
