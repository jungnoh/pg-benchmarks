#!/usr/bin/env python3
"""Single-pass streaming parser for pg_page_intervals.bt output."""

import re
import sys


def parse_stream(fh):
    fnames = {}  # ino -> filename
    mins = {}  # (ino, blk) -> min_ns
    procs = {}  # ino -> {comm: count}

    section = None
    re_fname = re.compile(r"@fname\[(\d+)\]:\s*(.+)")
    re_min = re.compile(r"@_min\[(\d+),\s*(\d+)\]:\s*(\d+)")
    re_proc = re.compile(r"@procs\[(\d+)\]:\s*(\d+)")

    for line in fh:
        if "===FNAME_START===" in line:
            section = "fname"
            continue
        if "===MIN_NS_START===" in line:
            section = "min"
            continue
        if "===PROCS_START===" in line:
            section = "proc"
            continue
        if "END===" in line:
            section = None
            continue

        if section == "fname":
            m = re_fname.match(line)
            if m:
                fnames[int(m[1])] = m[2].strip()

        elif section == "min":
            m = re_min.match(line)
            if m:
                mins[(int(m[1]), int(m[2]))] = int(m[3])

        elif section == "proc":
            m = re_proc.match(line)
            if m:
                procs[int(m[1])] = int(m[2])

    return fnames, mins, procs


def human_ns(ns):
    if ns < 1_000:
        return f"{ns} ns"
    if ns < 1_000_000:
        return f"{ns / 1e3:.1f} µs"
    if ns < 1_000_000_000:
        return f"{ns / 1e6:.2f} ms"
    return f"{ns / 1e9:.3f} s"


def main():
    fh = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
    fnames, mins, procs = parse_stream(fh)

    sorted_blocks = reversed(sorted(mins.items(), key=lambda kv: kv[1]))

    print(
        f"{'MIN INTERVAL':>14} {'NS':>14} {'FILENAME':<30}  {'OFFSET':>10}  {'BLK':>8}  {'INODE':>10}  {'ACCESSES':>10}"
    )
    print("-" * 100)
    for (ino, blk), ns in sorted_blocks:
        # Skip intervals less than 1s
        if ns < 1_000_000_000:
            continue
        fname = fnames.get(ino, "?")
        count = procs.get(ino, 0)
        print(
            f"{human_ns(ns):>14}  "
            f"{ns:>14}  "
            f"{fname:<30}  "
            f"{blk * 8192:>10}  "
            f"{blk:>8}  "
            f"{ino:>10}  "
            f"{count:>10}"
        )


if __name__ == "__main__":
    main()
