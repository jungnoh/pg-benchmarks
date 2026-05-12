import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import paramiko

from .target_run import (
    LogConfig,
    PgTarget,
    SshTarget,
    pg_file,
    pg_queries,
    ssh_command,
    ssh_retrieve_directory,
    ssh_retrieve_file,
)

CMD_DISABLE_SWAP = "sudo swapoff -a"
CMD_SYNC = "sudo sync"
CMD_DROP_CACHES = "sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'"


def cmd_pg_ctlcuster_restart(version: str, name: str = "main") -> str:
    """
    Returns the command to restart the PostgreSQL cluster.
    """
    return f"sudo pg_ctlcluster {version} {name} restart"


def ssh_get_memory_size(target: SshTarget) -> int:
    """
    Returns the memory size in KB.
    """
    result = ssh_command(target, "cat /proc/meminfo | grep MemTotal | awk '{print $2}'")
    return int(result.stdout.strip())


def pg_clear_stats(
    target: PgTarget, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Clears the statistics for the PostgreSQL database.
    """
    return pg_queries(
        target,
        [
            "SELECT pg_stat_statements_reset();",
            "SELECT pg_stat_kcache_reset();",
            "SELECT pg_wait_sampling_reset_profile();",
            "SELECT pg_stat_reset();",
        ],
        log,
    )


def pg_print_stats(
    target: PgTarget, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Prints the statistics for the PostgreSQL database.
    """
    return pg_queries(
        target,
        [
            "SELECT * FROM pg_stat_bgwriter;",
            "SELECT * FROM pg_stat_io;",
            "SELECT * FROM pg_stat_wal;",
        ],
        log,
    )


def pg_vacuum_analyze(
    target: PgTarget, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    VACUUM (ANALYZE) all tables in the target database, then CHECKPOINT to
    flush dirty buffers to disk. Standardizes dead-tuple bloat at run start
    so autovacuum catch-up work happens outside the measurement window.

    Wraps the VACUUM in ALTER SYSTEM SET *_cost_delay=0 + pg_reload_conf()
    so it runs unthrottled, then RESETs afterward. psql -f processes all
    statements sequentially without aborting on per-statement errors
    (ON_ERROR_STOP unset), so the RESETs still execute if the VACUUM
    itself errors — leaving the cluster's cost-delay settings restored.
    """
    return pg_queries(
        target,
        [
            "ALTER SYSTEM SET autovacuum_vacuum_cost_delay = 0;",
            "ALTER SYSTEM SET vacuum_cost_delay = 0;",
            "SELECT pg_reload_conf();",
            "VACUUM (ANALYZE);",
            "CHECKPOINT;",
            "ALTER SYSTEM RESET autovacuum_vacuum_cost_delay;",
            "ALTER SYSTEM RESET vacuum_cost_delay;",
            "SELECT pg_reload_conf();",
        ],
        log,
    )


def pg_build_configs(system_mem_size_gb: int) -> Dict[str, str]:
    """
    Returns a dictionary of PostgreSQL configurations as guided by pgtune.

    Reference: https://github.com/le0pard/pgtune/blob/master/src/features/configuration/configurationSlice.js
    """
    mem_mb = system_mem_size_gb * 1024
    return {
        **pg_default_configs(),
        "shared_buffers": f"{(mem_mb * 0.25):.0f}MB",
        "effective_cache_size": f"{(mem_mb * 0.75):.0f}MB",
        "maintenance_work_mem": f"{(mem_mb / 16):.0f}MB",
        "random_page_cost": "1.1",
        "checkpoint_completion_target": "0.9",
        "effective_io_concurrency": "200",
        "min_wal_size": "4GB",
        "max_wal_size": "16GB",
    }


def pg_default_configs() -> Dict[str, str]:
    """
    Returns the default configurations for the PostgreSQL database.
    Default values reference: https://postgresqlco.nf/doc/en/param/
    """
    return {
        "track_io_timing": "on",
        "shared_buffers": "128MB",
        "effective_cache_size": "4GB",
        "maintenance_work_mem": "64MB",
        "random_page_cost": "4",
        "checkpoint_completion_target": "0.9",
        "effective_io_concurrency": "1",
        "min_wal_size": "80MB",
        "max_wal_size": "1GB",
    }


def pg_apply_configs(
    target: PgTarget, configs: Dict[str, str], log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Applies the configurations to the PostgreSQL database.
    """
    return pg_queries(
        target, [f"ALTER SYSTEM SET {k} = '{v}';" for k, v in configs.items()], log
    )


def pg_analyze_waits(
    target: PgTarget, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Analyzes the waits for the PostgreSQL database.
    """
    return pg_file(target, Path(__file__).parent / "pg_analyze_waits.sql", log)


def pg_wait_events(
    target: PgTarget, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Lists wait events for the PostgreSQL database.
    """
    return pg_file(target, Path(__file__).parent / "pg_wait_events.sql", log)


class PgStatLogger:
    def __init__(self, ssh_target: SshTarget, pg_target: PgTarget):
        self.id = str(uuid.uuid4())
        self.pg_target = pg_target
        self.ssh_target = ssh_target
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.remote_trace_pid = None

    def prepare(self):
        print("Connecting to the target")
        self.ssh.connect(
            self.ssh_target.hostname,
            port=self.ssh_target.port,
            username=self.ssh_target.username,
            password=self.ssh_target.password,
        )
        print("Connected to the target")

    def start(self):
        print("Starting the logger")
        cmd = (
            'echo "select now(), sum(total_exec_time) exec_time, sum(calls) calls from pg_stat_statements; \\watch 0.5"'
            + f"| sudo -u {self.pg_target.username} psql -t"
            + f"> /tmp/probe-{self.id}.out 2>&1 & echo $!"
        )
        _, stdout, _ = self.ssh.exec_command(cmd)
        pid = int(stdout.read().decode().strip())
        print(f"Logger script started with PID: {pid}")
        self.remote_trace_pid = pid

    def stop(self, log: LogConfig):
        if self.remote_trace_pid is None:
            print("No log script is running")
            return
        self.ssh.exec_command(f"sudo kill -INT {self.remote_trace_pid}")

        output_folder = Path(log.log_file_folder()) / "after" / "stat-queries"
        output_folder.mkdir(parents=True, exist_ok=True)
        raw_log_remote_path = f"/tmp/probe-{self.id}.out"
        raw_log_local_path = str(output_folder / "throughput.log")
        ssh_retrieve_file(self.ssh_target, raw_log_remote_path, raw_log_local_path)

        timestamps, exec_times, calls = self._parse_probe_log(raw_log_local_path)
        print(f"Parsed {len(timestamps)} samples from {raw_log_local_path}")

        tp_times, tp_values, lat_values = self._compute_metrics(
            timestamps, exec_times, calls
        )
        self._plot(
            tp_times, tp_values, lat_values, str(output_folder / "throughput.png")
        )

    def _parse_probe_log(self, filepath: str):
        """Parse probe log lines into lists of (timestamp, exec_time, calls)."""
        timestamps = []
        exec_times = []
        calls = []

        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("--") or line.startswith("Watch"):
                    continue

                parts = [p.strip() for p in line.split("|")]
                if len(parts) != 3:
                    continue

                try:
                    # Timestamp may have timezone offset — strip it for simplicity
                    ts_raw = re.sub(r"[+-]\d{2}$", "", parts[0].strip())
                    ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S.%f")
                    et = float(parts[1])
                    c = int(parts[2])
                except (ValueError, IndexError):
                    continue

                timestamps.append(ts)
                exec_times.append(et)
                calls.append(c)

        return timestamps, exec_times, calls

    def _compute_metrics(self, timestamps, exec_times, calls):
        """Compute per-interval throughput (calls/sec) and avg latency (ms/call)."""
        times = []
        tp_values = []
        lat_values = []

        for i in range(1, len(timestamps)):
            dt = (timestamps[i] - timestamps[i - 1]).total_seconds()
            if dt <= 0:
                continue
            dcalls = calls[i] - calls[i - 1]
            dexec = exec_times[i] - exec_times[i - 1]
            if dcalls <= 0:
                continue

            times.append(timestamps[i])
            tp_values.append(dcalls / dt)
            lat_values.append(dexec / dcalls)  # ms per call (exec_time is in ms)

        return times, tp_values, lat_values

    def _plot(self, times, tp_values, lat_values, output_path="throughput.png"):
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

        # --- Throughput subplot ---
        ax1.plot(times, tp_values, linewidth=0.8, color="#3366cc")
        ax1.fill_between(times, tp_values, alpha=0.15, color="#3366cc")
        ax1.set_title("Query Throughput Over Time", fontsize=14)
        ax1.set_ylabel("Throughput (calls/sec)")
        ax1.grid(True, alpha=0.3)

        # --- Avg latency subplot ---
        ax2.plot(times, lat_values, linewidth=0.8, color="#cc3333")
        ax2.fill_between(times, lat_values, alpha=0.15, color="#cc3333")
        ax2.set_title("Average Query Latency Over Time", fontsize=14)
        ax2.set_xlabel("Time")
        ax2.set_ylabel("Avg Latency (ms/call)")
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        ax2.grid(True, alpha=0.3)

        fig.autofmt_xdate()
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"Saved plot to {output_path}")
        plt.close()


class PageEvictTracker:
    REMOTE_OUTPUT_DIR = "page-monitor"
    SHUTDOWN_TIMEOUT_SECS = 300

    def __init__(self, ssh_target: SshTarget, run_id: str):
        self.id = str(uuid.uuid4())
        self.ssh_target = ssh_target
        self.run_id = run_id
        self.screen_session = f"page-evict-{self.id}"
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.started = False

    def prepare(self):
        print("Connecting to the target")
        self.ssh.connect(
            self.ssh_target.hostname,
            port=self.ssh_target.port,
            username=self.ssh_target.username,
            password=self.ssh_target.password,
        )
        print("Connected to the target")

    def start(self):
        cmd = (
            f"bash -lc 'cd ~ && screen -dmS {self.screen_session} "
            f"sudo ./page-evict-tracker --root /mnt/psql/18/ "
            f"--log-level debug {self.run_id}'"
        )
        print(f"Starting page-evict-tracker: {cmd}")
        self.ssh.exec_command(cmd)
        self.started = True

    def stop(self, log: LogConfig):
        if not self.started:
            print("No page-evict-tracker is running")
            return

        pgrep_pattern = f"page-evict-tracker.*{self.run_id}"

        # Pre-check: if the binary already exited, skip the pkill so we
        # don't signal anything that happens to share the pattern.
        _, stdout, _ = self.ssh.exec_command(f"pgrep -f '{pgrep_pattern}'")
        if stdout.read().decode().strip() == "":
            print("page-evict-tracker already exited; skipping SIGINT")
        else:
            self.ssh.exec_command(f"sudo pkill -INT -f '{pgrep_pattern}'")

            wait_count = int(self.SHUTDOWN_TIMEOUT_SECS / 0.5)
            for i in range(wait_count):
                _, stdout, _ = self.ssh.exec_command(f"pgrep -f '{pgrep_pattern}'")
                if stdout.read().decode().strip() == "":
                    print("page-evict-tracker stopped")
                    break
                if i == wait_count - 1:
                    print("page-evict-tracker did not stop within timeout")
                    break
                time.sleep(0.5)

        # Reap the (now likely empty) screen session either way.
        self.ssh.exec_command(f"screen -X -S {self.screen_session} quit")

        remote_dir = f"~/{self.REMOTE_OUTPUT_DIR}/{self.run_id}"
        _, stdout, _ = self.ssh.exec_command(
            f"test -d {remote_dir} && echo yes || echo no"
        )
        if stdout.read().decode().strip() == "yes":
            local_dir = Path(log.log_file_folder()) / "after" / "page_evict_tracker"
            local_dir.mkdir(parents=True, exist_ok=True)
            ssh_retrieve_directory(self.ssh_target, remote_dir, str(local_dir))
            self.ssh.exec_command(f"sudo rm -rf {remote_dir}")
        else:
            print(
                f"page-evict-tracker output dir {remote_dir} does not exist; "
                f"skipping retrieval"
            )

        self.started = False


class CacheExtPolicy:
    BINARY_DIR = "./cache-ext-policies/out"
    DEFAULT_BINARY_NAME = "cache_ext_psql_noop"
    WATCH_DIR = "/mnt/psql/18"
    CGROUP_PATH = (
        "/sys/fs/cgroup/system.slice/system-postgresql.slice/postgresql@18-main.service"
    )
    STARTUP_RETRY_ATTEMPTS = 5
    STARTUP_PROBE_DELAY_SECS = 2
    SHUTDOWN_TIMEOUT_SECS = 20

    def __init__(
        self,
        ssh_target: SshTarget,
        binary_name: str = DEFAULT_BINARY_NAME,
        extra_args: str = "",
    ):
        self.id = str(uuid.uuid4())
        self.ssh_target = ssh_target
        self.binary_name = binary_name
        self.binary_path = f"{self.BINARY_DIR}/{binary_name}.out"
        self.pgrep_pattern = f"{binary_name}.out"
        self.extra_args = extra_args
        self.screen_session: Optional[str] = None
        self.remote_log_path: Optional[str] = None
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.started = False
        self.timed_out = False
        self._tail_stop: Optional[threading.Event] = None
        self._tail_thread: Optional[threading.Thread] = None

    def prepare(self):
        print("Connecting to the target")
        self.ssh.connect(
            self.ssh_target.hostname,
            port=self.ssh_target.port,
            username=self.ssh_target.username,
            password=self.ssh_target.password,
        )
        print("Connected to the target")

    def start(self):
        for attempt in range(1, self.STARTUP_RETRY_ATTEMPTS + 1):
            session_name = f"cache-ext-{self.id}-{attempt}"
            log_path = f"/tmp/cache-ext-{self.id}-{attempt}.log"
            extra = f" {self.extra_args}" if self.extra_args else ""
            cmd = (
                f"bash -lc 'cd ~ && touch {log_path} && "
                f"screen -dmS {session_name} -L -Logfile {log_path} "
                f"sudo {self.binary_path} "
                f"--watch_dir {self.WATCH_DIR} "
                f"--cgroup_path {self.CGROUP_PATH}"
                f"{extra}'"
            )
            print(f"Starting cache-ext policy (attempt {attempt}): {cmd}")
            self.ssh.exec_command(cmd)
            time.sleep(self.STARTUP_PROBE_DELAY_SECS)

            _, stdout, _ = self.ssh.exec_command(f"pgrep -f '{self.pgrep_pattern}'")
            if stdout.read().decode().strip() != "":
                self.screen_session = session_name
                self.remote_log_path = log_path
                self.started = True
                self._start_tail_thread()
                return

            print(
                f"cache-ext policy failed to start "
                f"(attempt {attempt}/{self.STARTUP_RETRY_ATTEMPTS})"
            )
            self.ssh.exec_command(f"screen -X -S {session_name} quit")

        raise RuntimeError(
            f"cache-ext policy failed to start after "
            f"{self.STARTUP_RETRY_ATTEMPTS} attempts"
        )

    def _start_tail_thread(self):
        self._tail_stop = threading.Event()
        self._tail_thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._tail_thread.start()

    def _tail_loop(self):
        transport = self.ssh.get_transport()
        if transport is None:
            return
        channel = transport.open_session()
        channel.exec_command(f"tail -F {self.remote_log_path}")
        channel.settimeout(0.5)
        try:
            while not self._tail_stop.is_set():
                try:
                    data = channel.recv(4096)
                    if not data:
                        break
                    sys.stdout.write(data.decode(errors="replace"))
                    sys.stdout.flush()
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            try:
                channel.close()
            except Exception:
                pass

    def stop(self, log: LogConfig):
        if not self.started:
            print("No cache-ext policy is running")
            return

        # Pre-check: if the binary is no longer running on the remote
        # (e.g., it crashed during the run), skip the pkill entirely so
        # we don't accidentally signal an unrelated process that happens
        # to share the binary name pattern.
        _, stdout, _ = self.ssh.exec_command(f"pgrep -f '{self.pgrep_pattern}'")
        if stdout.read().decode().strip() == "":
            print("cache-ext policy already exited; skipping SIGINT")
            stopped = True
        else:
            self.ssh.exec_command(f"sudo pkill -INT -f '{self.pgrep_pattern}'")

            stopped = False
            wait_count = int(self.SHUTDOWN_TIMEOUT_SECS / 0.5)
            for _ in range(wait_count):
                _, stdout, _ = self.ssh.exec_command(f"pgrep -f '{self.pgrep_pattern}'")
                if stdout.read().decode().strip() == "":
                    stopped = True
                    print("cache-ext policy stopped")
                    break
                time.sleep(0.5)

            if not stopped:
                self.timed_out = True
                print(
                    f"cache-ext policy did not exit within "
                    f"{self.SHUTDOWN_TIMEOUT_SECS}s of SIGINT; "
                    f"leaving screen session '{self.screen_session}' alive "
                    f"to avoid SIGKILL escalation"
                )

        if self._tail_stop is not None:
            self._tail_stop.set()
        if self._tail_thread is not None:
            self._tail_thread.join(timeout=2)

        # Only reap the screen session when the binary has already exited.
        # `screen -X quit` would SIGHUP and then SIGKILL any surviving
        # children, which violates the SIGINT-only contract.
        if stopped and self.screen_session is not None:
            self.ssh.exec_command(f"screen -X -S {self.screen_session} quit")
        self.started = False
