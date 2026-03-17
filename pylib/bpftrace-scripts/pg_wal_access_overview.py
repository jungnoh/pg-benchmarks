#!/usr/bin/env python3

import argparse
import re
import sys

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np

LINE_RE = re.compile(r"^([RW])/(\d+)/([\dA-Fa-f]+)/(\d+)/(\d+)$")
WAL_SEGMENT_SIZE = 16 * 1024 * 1024  # 16 MB


def parse_wal_filename(name: str) -> tuple[int, int, int]:
    """Extract (timeline, log_id, segment_no) from a 24-char hex WAL filename."""
    timeline = int(name[0:8], 16)
    log_id = int(name[8:16], 16)
    seg_no = int(name[16:24], 16)
    return timeline, log_id, seg_no


def global_wal_offset(log_id: int, seg_no: int, offset: int) -> int:
    return (log_id * 256 + seg_no) * WAL_SEGMENT_SIZE + offset


def parse_log(path: str):
    ops = []
    with open(path) as f:
        for line in f:
            m = LINE_RE.match(line.strip())
            if not m:
                continue
            rw = m.group(1)
            t_ns = int(m.group(2))
            tl, log_id, seg_no = parse_wal_filename(m.group(3))
            offset = int(m.group(4))
            size = int(m.group(5))
            g_off = global_wal_offset(log_id, seg_no, offset)
            ops.append((rw, t_ns, log_id, seg_no, offset, size, g_off))
    return ops


def build_figures(ops, output_path: str | None):
    if not ops:
        print("No matching log lines found.", file=sys.stderr)
        sys.exit(1)

    rw = np.array([o[0] for o in ops])
    t_ns = np.array([o[1] for o in ops], dtype=np.float64)
    seg_offset = np.array([o[4] for o in ops], dtype=np.float64)
    sizes = np.array([o[5] for o in ops], dtype=np.float64)
    g_off = np.array([o[6] for o in ops], dtype=np.float64)

    t_sec = t_ns / 1e9
    g_off_mb = g_off / (1024 * 1024)
    seg_off_mb = seg_offset / (1024 * 1024)
    sizes_kb = sizes / 1024

    w_mask = rw == "W"
    r_mask = rw == "R"
    has_reads = r_mask.any()

    fig = plt.figure(figsize=(20, 22), constrained_layout=True)
    fig.suptitle("PostgreSQL WAL I/O Access Patterns", fontsize=16, fontweight="bold")

    gs = fig.add_gridspec(4, 2, height_ratios=[3, 2, 2, 2])

    # ── Panel 1: Spatio-temporal heatmap (global WAL offset vs time) ─────
    ax_heat = fig.add_subplot(gs[0, :])
    time_bins = min(600, max(100, len(ops) // 200))
    offset_bins = 200
    t_edges = np.linspace(t_sec.min(), t_sec.max(), time_bins + 1)
    off_edges = np.linspace(g_off_mb.min(), g_off_mb.max(), offset_bins + 1)

    total_bytes_map = np.zeros((offset_bins, time_bins))
    t_idx = np.clip(np.searchsorted(t_edges, t_sec) - 1, 0, time_bins - 1)
    o_idx = np.clip(np.searchsorted(off_edges, g_off_mb) - 1, 0, offset_bins - 1)
    for i in range(len(ops)):
        total_bytes_map[o_idx[i], t_idx[i]] += sizes[i]

    total_kb_map = total_bytes_map / 1024
    total_kb_map[total_kb_map == 0] = np.nan

    im = ax_heat.pcolormesh(
        t_edges,
        off_edges,
        total_kb_map,
        cmap="inferno",
        norm=mcolors.LogNorm(
            vmin=np.nanmin(total_kb_map[total_kb_map > 0]), vmax=np.nanmax(total_kb_map)
        ),
        rasterized=True,
    )
    fig.colorbar(im, ax=ax_heat, label="KB written per bin", pad=0.01)
    ax_heat.set_xlabel("Time (s)")
    ax_heat.set_ylabel("Global WAL position (MB)")
    ax_heat.set_title("Spatio-Temporal Heatmap: bytes written by time and WAL position")

    # ── Panel 2: Throughput over time ────────────────────────────────────
    ax_tp = fig.add_subplot(gs[1, 0])
    tp_bins = min(300, max(50, len(ops) // 400))
    tp_edges = np.linspace(t_sec.min(), t_sec.max(), tp_bins + 1)
    tp_idx = np.clip(np.searchsorted(tp_edges, t_sec[w_mask]) - 1, 0, tp_bins - 1)
    throughput = np.zeros(tp_bins)
    for i, idx in enumerate(tp_idx):
        throughput[idx] += sizes[w_mask][i]

    bin_width_s = tp_edges[1] - tp_edges[0]
    throughput_mbs = throughput / (1024 * 1024) / bin_width_s

    tp_centers = (tp_edges[:-1] + tp_edges[1:]) / 2
    ax_tp.fill_between(tp_centers, throughput_mbs, alpha=0.5, color="steelblue")
    ax_tp.plot(tp_centers, throughput_mbs, linewidth=0.8, color="steelblue")
    ax_tp.set_xlabel("Time (s)")
    ax_tp.set_ylabel("Throughput (MB/s)")
    ax_tp.set_title("WAL Write Throughput Over Time")
    ax_tp.set_xlim(t_sec.min(), t_sec.max())

    # ── Panel 3: Write size distribution ─────────────────────────────────
    ax_sz = fig.add_subplot(gs[1, 1])
    log_sizes = np.log2(sizes_kb[w_mask])
    bin_edges = np.arange(np.floor(log_sizes.min()), np.ceil(log_sizes.max()) + 1, 0.5)
    ax_sz.hist(
        log_sizes, bins=bin_edges, color="coral", edgecolor="white", linewidth=0.5
    )
    tick_positions = np.arange(np.floor(log_sizes.min()), np.ceil(log_sizes.max()) + 1)
    ax_sz.set_xticks(tick_positions)
    ax_sz.set_xticklabels(
        [f"{2 ** int(x):.0f}" if x >= 0 else f"{2**x:.1f}" for x in tick_positions]
    )
    ax_sz.set_xlabel("Write size (KB)")
    ax_sz.set_ylabel("Count")
    ax_sz.set_title("Write Size Distribution (log₂ scale)")

    # ── Panel 4: Offset within segment over time ─────────────────────────
    ax_seg = fig.add_subplot(gs[2, :])
    sample_n = min(len(ops), 40000)
    sample_idx = np.sort(
        np.random.default_rng(42).choice(len(ops), sample_n, replace=False)
    )
    ax_seg.scatter(
        t_sec[sample_idx],
        seg_off_mb[sample_idx],
        s=0.3,
        alpha=0.4,
        c="steelblue",
        rasterized=True,
    )
    ax_seg.set_xlabel("Time (s)")
    ax_seg.set_ylabel("Offset within WAL segment (MB)")
    ax_seg.set_title("Intra-Segment Offset Over Time (sampled)")
    ax_seg.set_ylim(-0.2, WAL_SEGMENT_SIZE / (1024 * 1024) + 0.2)
    ax_seg.set_xlim(t_sec.min(), t_sec.max())

    # ── Panel 5: IOPS over time ──────────────────────────────────────────
    ax_iops = fig.add_subplot(gs[3, 0])
    iops_vals = np.zeros(tp_bins)
    tp_idx_all = np.clip(np.searchsorted(tp_edges, t_sec[w_mask]) - 1, 0, tp_bins - 1)
    for idx in tp_idx_all:
        iops_vals[idx] += 1
    iops_rate = iops_vals / bin_width_s
    ax_iops.fill_between(tp_centers, iops_rate, alpha=0.5, color="seagreen")
    ax_iops.plot(tp_centers, iops_rate, linewidth=0.8, color="seagreen")
    ax_iops.set_xlabel("Time (s)")
    ax_iops.set_ylabel("IOPS (writes/s)")
    ax_iops.set_title("WAL Write IOPS Over Time")
    ax_iops.set_xlim(t_sec.min(), t_sec.max())

    # ── Panel 6: Mean write size over time ───────────────────────────────
    ax_avg = fig.add_subplot(gs[3, 1])
    mean_sz = np.zeros(tp_bins)
    count_per_bin = np.zeros(tp_bins)
    for i, idx in enumerate(tp_idx):
        mean_sz[idx] += sizes_kb[w_mask][i]
        count_per_bin[idx] += 1
    nonzero = count_per_bin > 0
    mean_sz[nonzero] /= count_per_bin[nonzero]
    ax_avg.plot(tp_centers[nonzero], mean_sz[nonzero], linewidth=1, color="darkorange")
    ax_avg.set_xlabel("Time (s)")
    ax_avg.set_ylabel("Mean write size (KB)")
    ax_avg.set_title("Mean Write Size Over Time")
    ax_avg.set_xlim(t_sec.min(), t_sec.max())

    if output_path:
        fig.savefig(output_path, dpi=150)
        print(f"Saved to {output_path}")
    else:
        plt.show()


def main():
    parser = argparse.ArgumentParser(
        description="Visualize PostgreSQL WAL I/O patterns from bpftrace logs"
    )
    parser.add_argument("logfile", help="Path to the bpftrace WAL access log file")
    args = parser.parse_args()

    print(f"Parsing {args.logfile} ...")
    ops = parse_log(args.logfile)
    print(f"Parsed {len(ops)} I/O operations.")
    build_figures(ops, "/tmp/pg_wal_access_overview.png")


if __name__ == "__main__":
    main()
