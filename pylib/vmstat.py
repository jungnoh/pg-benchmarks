"""Compare two /proc/vmstat snapshots and show differences."""

import re
from typing import Optional
from pylib.target_run import LogConfig

VMSTAT_PATTERN = re.compile(r"^([a-z_\d]+) (\d+)$")


def parse_file(filename):
    """Parse vmstat file into dict of {metric: value}."""
    stats = {}
    with open(filename) as f:
        for line in f:
            match = VMSTAT_PATTERN.match(line)
            if match:
                stats[match.group(1)] = int(match.group(2))
    return stats


def diff(before_path: str, after_path: str, log: Optional[LogConfig] = None):
    before = parse_file(before_path)
    after = parse_file(after_path)

    result = []

    result.append(f"{'Metric':<32} {'Before':>14} {'After':>14} {'Delta':>14}")
    result.append("-" * 76)

    for key in sorted(after.keys()):
        if key in before:
            delta = after[key] - before[key]
            if delta != 0:  # only show changed values
                result.append(
                    f"{key:<32} {before[key]:>14} {after[key]:>14} {delta:>+14}"
                )

    if log:
        log.ensure_log_folder()
        with open(log.log_file_path(), "w") as f:
            for line in result:
                f.write(line + "\n")
    else:
        for line in result:
            print(line)
    return result
