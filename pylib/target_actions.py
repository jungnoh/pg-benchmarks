from .target_run import SshTarget, PgTarget, ssh_command, pg_file, pg_queries, LogConfig
from typing import Dict, Optional
import subprocess
from pathlib import Path

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


def pg_build_configs(system_mem_size_gb: int) -> Dict[str, str]:
    """
    Returns a dictionary of PostgreSQL configurations as guided by pgtune.

    Reference: https://github.com/le0pard/pgtune/blob/master/src/features/configuration/configurationSlice.js
    """
    mem_mb = system_mem_size_gb * 1024
    return {
        "shared_buffers": f"{(mem_mb * 0.25):.0f}MB",
        "effective_cache_size": f"{(mem_mb * 0.75):.0f}MB",
        "maintenance_work_mem": f"{(mem_mb / 16):.0f}MB",
        "random_page_cost": "1.1",
        "checkpoint_completion_target": "0.9",
        "effective_io_concurrency": "200",
        "min_wal_size": "4GB",
        "max_wal_size": "16GB",
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
