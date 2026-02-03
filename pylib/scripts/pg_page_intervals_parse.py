#!/usr/bin/env python3
"""Single-pass streaming parser for pg_page_intervals.bt output."""

import re
import sys


def parse_stream(fh):
    fnames = {}  # (ino) -> filename
    mins = {}  # (ino, pg) -> min_ns
    procs = {}  # (ino, pg) -> ["comm(pid)xN", ...]

    section = None
    re_fname = re.compile(r"@fname\[(\d+)\]:\s*(.+)")
    re_min = re.compile(r"@_min\[(\d+),\s*(\d+)\]:\s*(\d+)")
    re_proc = re.compile(
        r"@procs\[(\d+),\s*(\d+),\s*([^,]+),\s*(\d+)\]:\s*(\d+)"
    )

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
                fnames[(int(m[1]), int(m[2]))] = m[3].strip()

        elif section == "min":
            m = re_min.match(line)
            if m:
                mins[(int(m[1]), int(m[2]), int(m[3]))] = int(m[4])

        elif section == "proc":
            m = re_proc.match(line)
            if m:
                key = (int(m[1]), int(m[2]), int(m[3]))
                procs.setdefault(key, []).append(f"{m[4].strip()}({m[5]})x{m[6]}")

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

    sorted_pages = sorted(mins.items(), key=lambda kv: kv[1])

    print(
        f"{'MIN INTERVAL':>14}  {'FILENAME':<30}  {'OFFSET':>10}  {'PAGE':>8}  PROCESSES"
    )
    print("-" * 110)
    for (ino, pg), ns in sorted_pages:
        print(
            f"{human_ns(ns):>14}  "
            f"{fnames.get((ino), '?'):<30}  "
            f"{pg * 4096:>10}  "
            f"{pg:>8}  "
            f"{', '.join(procs.get((ino, pg), ['?']))}"
        )


if __name__ == "__main__":
    main()
