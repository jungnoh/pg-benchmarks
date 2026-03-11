#!/usr/bin/env python3

import re
import sys

lines = []
file = open(sys.argv[1], "r") if len(sys.argv) > 1 else sys.stdin
for line in file:
    m = re.match(r"^(\d+)\s+(\d+)\s+(\S+)", line.strip())
    if m:
        inode, misses, path = m.group(1), int(m.group(2)), m.group(3)
        lines.append((inode, misses, path))

sorted_lines = sorted(lines, key=lambda x: x[1], reverse=True)
total_misses = sum(m for _, m, _ in sorted_lines)
wal_misses = sum(m for _, m, p in sorted_lines if re.match(r"^[0-9A-F]{24}$", p))
ratio = (wal_misses / total_misses * 100) if total_misses else 0

print(f"Total: {total_misses} / WAL: {wal_misses} / Ratio: {ratio:.1f}%")
print()

print("inode       misses    filename")
for inode, misses, path in sorted_lines:
    print(f"{inode:<12}{misses:<10}{path}")
