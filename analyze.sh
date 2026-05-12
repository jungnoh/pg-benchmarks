#!/usr/bin/env bash
# analyze.sh — summarize hammerdb TPC-C runs by group label.
#
# Usage:
#   ./analyze.sh                          # auto-discover all groups in logs/hammerdb/
#   ./analyze.sh baseline policy1 policy2 # restrict to listed groups (in order)
#
# A "group" matches log directories of the form
#   logs/hammerdb/tpcc-<vu>-<group>-<id>-sample<NN>/
# (the harness's standard layout; see hammerdb.py).
#
# For each group, prints three tables:
#   1) NOPM / TPM per sample + avg/min/max
#   2) workingset_refault_file and pgsteal_kswapd per-sample (after - before)
#   3) Eviction signature for the last sample's final per-second CSV:
#      total pages evicted, WAL full-segment vs partial-segment counts.
#
# The script reads files only — never modifies the run dirs.

set -euo pipefail

LOG_ROOT="${LOG_ROOT:-$(dirname "$0")/logs/hammerdb}"

if [[ ! -d "$LOG_ROOT" ]]; then
    echo "no log root at $LOG_ROOT" >&2
    exit 1
fi

# --- group discovery -------------------------------------------------------

# Resolve groups: each arg names a group; with no args, auto-discover from
# directory names. The "id" portion is the run timestamp; we keep the latest
# one per group (newest mtime).
# Tighten the wildcard so groups like "policy2" don't accidentally match
# "policy2-n5only" siblings — the run-id portion must be all digits.
resolve_dir_prefix() {
    local group=$1
    local newest_dir
    newest_dir=$(find "$LOG_ROOT" -maxdepth 1 -type d \
        -name "tpcc-*-${group}-[0-9]*-sample01" -printf '%T@\t%p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -f2) || true
    [[ -z "$newest_dir" ]] && return 1
    # strip "-sample01" suffix to get the per-sample prefix
    echo "${newest_dir%-sample01}"
}

discover_groups() {
    find "$LOG_ROOT" -maxdepth 1 -type d -name 'tpcc-*-sample01' -printf '%f\n' 2>/dev/null \
        | sed -E 's/^tpcc-[0-9]+-(.+)-[0-9]+-sample01$/\1/' \
        | awk '!seen[$0]++' || true
}

if [[ $# -gt 0 ]]; then
    RUN_GROUPS=("$@")
else
    mapfile -t RUN_GROUPS < <(discover_groups)
fi

if [[ ${#RUN_GROUPS[@]} -eq 0 ]]; then
    echo "no groups discovered under $LOG_ROOT" >&2
    exit 1
fi

# --- table 1: NOPM / TPM ---------------------------------------------------

print_nopm_table() {
    printf '%-26s %10s %10s %10s %10s %10s\n' \
        group nopm_avg nopm_min nopm_max tpm_avg samples
    printf '%-26s %10s %10s %10s %10s %10s\n' \
        '-----' '--------' '--------' '--------' '--------' '--------'

    for group in "${RUN_GROUPS[@]}"; do
        local prefix
        prefix=$(resolve_dir_prefix "$group" 2>/dev/null) || {
            printf '%-26s %s\n' "$group" "(no runs found)"; continue;
        }
        local nopm_vals tpm_vals
        nopm_vals=()
        tpm_vals=()
        for d in "$prefix"-sample*; do
            [[ -d "$d" && -f "$d/run.log" ]] || continue
            local line=""
            line=$(grep -E "TEST RESULT" "$d/run.log" 2>/dev/null | head -1) || true
            [[ -z "$line" ]] && continue
            local nopm tpm
            nopm=$(echo "$line" | sed -E 's/.*achieved ([0-9]+) NOPM.*/\1/')
            tpm=$(echo  "$line" | sed -E 's/.*from ([0-9]+) PostgreSQL.*/\1/')
            nopm_vals+=("$nopm")
            tpm_vals+=("$tpm")
        done
        if [[ ${#nopm_vals[@]} -eq 0 ]]; then
            printf '%-26s %s\n' "$group" "(incomplete)"
            continue
        fi
        local n_avg n_min n_max t_avg
        n_avg=$(printf '%s\n' "${nopm_vals[@]}" | awk '{s+=$1} END {printf "%.0f", s/NR}')
        n_min=$(printf '%s\n' "${nopm_vals[@]}" | sort -n | head -1)
        n_max=$(printf '%s\n' "${nopm_vals[@]}" | sort -n | tail -1)
        t_avg=$(printf '%s\n' "${tpm_vals[@]}"  | awk '{s+=$1} END {printf "%.0f", s/NR}')
        printf '%-26s %10s %10s %10s %10s %10d\n' \
            "$group" "$n_avg" "$n_min" "$n_max" "$t_avg" "${#nopm_vals[@]}"
    done
}

# --- table 2: refault / pgsteal --------------------------------------------

# Per-sample delta of /proc/vmstat counters (after - before). The harness
# captures full vmstat snapshots in before/vmstat.log and after/vmstat.log;
# `before` may be 0 (post-reboot reset) or a continuous counter.
read_vmstat_delta() {
    local sample_dir=$1 metric=$2
    local before after
    before=$(grep "^${metric}" "$sample_dir/before/vmstat.log" 2>/dev/null | awk '{print $2}')
    after=$(grep  "^${metric}" "$sample_dir/after/vmstat.log"  2>/dev/null | awk '{print $2}')
    [[ -z "$before" || -z "$after" ]] && { echo ""; return; }
    echo $((after - before))
}

print_refault_table() {
    printf '%-26s %14s %14s %14s %14s\n' \
        group refault_avg refault_max pgsteal_avg pgsteal_max
    printf '%-26s %14s %14s %14s %14s\n' \
        '-----' '------------' '------------' '------------' '------------'

    for group in "${RUN_GROUPS[@]}"; do
        local prefix
        prefix=$(resolve_dir_prefix "$group" 2>/dev/null) || continue
        local refaults=() pgsteals=()
        for d in "$prefix"-sample*; do
            [[ -d "$d" && -f "$d/before/vmstat.log" && -f "$d/after/vmstat.log" ]] || continue
            local rf ps
            rf=$(read_vmstat_delta "$d" "workingset_refault_file") || true
            ps=$(read_vmstat_delta "$d" "pgsteal_kswapd") || true
            [[ -n "$rf" ]] && refaults+=("$rf")
            [[ -n "$ps" ]] && pgsteals+=("$ps")
        done
        if [[ ${#refaults[@]} -eq 0 ]]; then
            printf '%-26s %s\n' "$group" "(no vmstat data)"; continue
        fi
        local rf_avg rf_max ps_avg ps_max
        rf_avg=$(printf '%s\n' "${refaults[@]}" | awk '{s+=$1} END {printf "%.1fM", s/NR/1e6}')
        rf_max=$(printf '%s\n' "${refaults[@]}" | sort -n | tail -1 | awk '{printf "%.1fM", $1/1e6}')
        ps_avg=$(printf '%s\n' "${pgsteals[@]}" | awk '{s+=$1} END {printf "%.1fM", s/NR/1e6}')
        ps_max=$(printf '%s\n' "${pgsteals[@]}" | sort -n | tail -1 | awk '{printf "%.1fM", $1/1e6}')
        printf '%-26s %14s %14s %14s %14s\n' \
            "$group" "$rf_avg" "$rf_max" "$ps_avg" "$ps_max"
    done
}

# --- table 3: eviction signature -------------------------------------------

# The page_evict_tracker emits one CSV per second. The "last" CSV captures
# the most recent eviction wave; partial WAL evictions (< 4096 pages on a
# single segment) are the policy_tpcc N5 watermark signature.
last_csv_for() {
    local sample_dir=$1
    find "$sample_dir/after/page_evict_tracker" -name '*.csv' \
        -path '*/page-evictions/*' -printf '%T@\t%p\n' 2>/dev/null \
        | sort -rn | head -1 | cut -f2 || true
}

print_eviction_table() {
    printf '%-26s %14s %12s %14s %16s\n' \
        group total_evicted wal_full wal_partial wal_total_pages
    printf '%-26s %14s %12s %14s %16s\n' \
        '-----' '------------' '----------' '------------' '--------------'

    for group in "${RUN_GROUPS[@]}"; do
        local prefix
        prefix=$(resolve_dir_prefix "$group" 2>/dev/null) || continue
        # Pick the highest-numbered sample with a populated after/ tree.
        local last_sample=""
        local sample_list
        sample_list=$(ls -d "$prefix"-sample* 2>/dev/null | sort -r) || true
        for d in $sample_list; do
            [[ -d "$d/after/page_evict_tracker" ]] && { last_sample=$d; break; }
        done
        if [[ -z "$last_sample" ]]; then
            printf '%-26s %s\n' "$group" "(no eviction data)"; continue
        fi
        local csv
        csv=$(last_csv_for "$last_sample")
        if [[ -z "$csv" ]]; then
            printf '%-26s %s\n' "$group" "(no eviction csv)"; continue
        fi
        local total wal_full wal_partial wal_pages
        total=$(tail -n +2 "$csv" | awk -F, '{s+=$2} END {printf "%d", s}')
        wal_full=$(tail -n +2 "$csv" \
            | awk -F, 'index($1,"pg_wal")==1 && $2==4096 {n++} END {print n+0}')
        wal_partial=$(tail -n +2 "$csv" \
            | awk -F, 'index($1,"pg_wal")==1 && $2!=4096 && $2<4096 {n++} END {print n+0}')
        wal_pages=$(tail -n +2 "$csv" \
            | awk -F, 'index($1,"pg_wal")==1 {s+=$2} END {printf "%d", s+0}')
        printf '%-26s %14s %12s %14s %16s\n' \
            "$group" "$total" "$wal_full" "$wal_partial" "$wal_pages"
    done
}

# --- main ------------------------------------------------------------------

echo "Groups: ${RUN_GROUPS[*]}"
echo
echo "=== 1) Throughput (NOPM / TPM) ==="
print_nopm_table
echo
echo "=== 2) Reclaim (refault / pgsteal_kswapd, per-run delta) ==="
print_refault_table
echo
echo "=== 3) Eviction signature (last per-second CSV of latest sample) ==="
print_eviction_table
