import math
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import target_actions as actions
from . import target_run as run
from . import vmstat
from .bpftrace import BpftraceClient, BpftraceConfig
from .target_run import LogConfig, PgTarget, SshTarget
from .util import read_config_file


def config_to_bool(config: Dict[str, str], key: str, default: bool = False) -> bool:
    value = config.get(key)
    if value is None:
        return default
    if value.lower() in ["true", "yes", "1"]:
        return True
    elif value.lower() in ["false", "no", "0"]:
        return False
    else:
        raise ValueError(f"Invalid boolean value: {value}")


def parse_cli_overrides(argv: List[str]) -> Tuple[Dict[str, str], List[str]]:
    """
    Strip recognized config-override flags from argv and return
    (overrides, remaining_argv). Recognized flags:

      --cache-ext-policy             -> CACHE_EXT_POLICY=true
      --no-cache-ext-policy          -> CACHE_EXT_POLICY=false
      --cache-ext-policy-binary NAME -> CACHE_EXT_POLICY_BINARY=NAME
      --cache-ext-policy-binary=NAME -> CACHE_EXT_POLICY_BINARY=NAME
    """
    overrides: Dict[str, str] = {}
    remaining: List[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--cache-ext-policy":
            overrides["CACHE_EXT_POLICY"] = "true"
            i += 1
        elif a == "--no-cache-ext-policy":
            overrides["CACHE_EXT_POLICY"] = "false"
            i += 1
        elif a == "--cache-ext-policy-binary":
            if i + 1 >= len(argv):
                raise ValueError(
                    "--cache-ext-policy-binary requires a value"
                )
            overrides["CACHE_EXT_POLICY_BINARY"] = argv[i + 1]
            i += 2
        elif a.startswith("--cache-ext-policy-binary="):
            overrides["CACHE_EXT_POLICY_BINARY"] = a.split("=", 1)[1]
            i += 1
        else:
            remaining.append(a)
            i += 1
    return overrides, remaining


class Suite(ABC):
    start_time: float = time.time()

    ssh_target: SshTarget
    pg_admin_target: PgTarget
    pg_runner_target: PgTarget

    @abstractmethod
    def prepare(self) -> None:
        pass

    @abstractmethod
    def run(self) -> None:
        pass

    @abstractmethod
    def cleanup(self) -> None:
        pass

    def run_id_suffix(self) -> str:
        return f"{self.start_time:.0f}"

    def log_config(self, action: str) -> LogConfig:
        return LogConfig(run_id=self.run_id_suffix(), action=action)


class SuiteRunner(ABC):
    bpftrace_clients: List[BpftraceClient] = []

    def __init__(
        self,
        config_file: str,
        suite: Suite,
        config_overrides: Optional[Dict[str, str]] = None,
    ):
        self.config = read_config_file(config_file)
        if config_overrides:
            self.config.update(config_overrides)
        self.suite = suite
        self.pg_version = self.config.get("PG_VERSION", 18)
        self.pg_cluster_name = self.config.get("PG_CLUSTER_NAME", "main")
        self.suite.pg_admin_target = PgTarget(
            username=self.config["PG_ADMIN_USERNAME"],
            password=self.config["PG_ADMIN_PASSWORD"],
            hostname=self.config["PG_ADMIN_HOST"],
            port=self.config["PG_ADMIN_PORT"],
            database=self.config["PG_ADMIN_DATABASE"],
        )
        self.suite.pg_runner_target = PgTarget(
            username=self.config["PG_RUNNER_USERNAME"],
            password=self.config["PG_RUNNER_PASSWORD"],
            hostname=self.config["PG_RUNNER_HOST"],
            port=self.config["PG_RUNNER_PORT"],
            database=self.config["PG_RUNNER_DATABASE"],
        )
        self.suite.ssh_target = SshTarget(
            username=self.config["SSH_USERNAME"],
            password=self.config["SSH_PASSWORD"],
            hostname=self.config["SSH_HOST"],
            port=self.config["SSH_PORT"],
        )
        self.pg_optimize_configs = config_to_bool(
            self.config, "PG_OPTIMIZE_CONFIGS", False
        )

        if config_to_bool(self.config, "BPFTRACE_RECLAIM_TS", False):
            bpftrace_config = BpftraceConfig.reclaim_ts(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )
        if config_to_bool(self.config, "BPFTRACE_CACHE_MISSES_BY_INO", False):
            bpftrace_config = BpftraceConfig.cache_misses_by_ino(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )
        if config_to_bool(self.config, "BPFTRACE_PG_PAGE_INTERVALS", False):
            bpftrace_config = BpftraceConfig.pg_page_intervals(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )
        if config_to_bool(self.config, "BPFTRACE_PG_WAL_ACCESS", False):
            bpftrace_config = BpftraceConfig.pg_wal_access(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )
        if config_to_bool(self.config, "BPFTRACE_WAL_PAGE_WORKING_SET", False):
            bpftrace_config = BpftraceConfig.wal_page_working_set(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )
        if config_to_bool(self.config, "BPFTRACE_WAL_CACHE_PAGES", False):
            bpftrace_config = BpftraceConfig.wal_cache_pages(self.config)
            self.bpftrace_clients.append(
                BpftraceClient(self.suite.ssh_target, bpftrace_config)
            )

        self.page_evict_tracker: Optional[actions.PageEvictTracker] = None
        if config_to_bool(self.config, "PAGE_EVICT_TRACKER", False):
            self.page_evict_tracker = actions.PageEvictTracker(
                self.suite.ssh_target,
                run_id=self.suite.run_id_suffix(),
            )

        self.cache_ext_policy: Optional[actions.CacheExtPolicy] = None
        if config_to_bool(self.config, "CACHE_EXT_POLICY", False):
            binary_name = (
                self.config.get("CACHE_EXT_POLICY_BINARY")
                or actions.CacheExtPolicy.DEFAULT_BINARY_NAME
            )
            self.cache_ext_policy = actions.CacheExtPolicy(
                self.suite.ssh_target, binary_name=binary_name
            )

    def run(self) -> None:
        self._run_before()
        self.suite.run()
        self._run_after()

    def _run_before(self) -> None:
        if self.pg_optimize_configs:
            mem_size_gb = self._detect_memory_size()
            print(f"Before: Applying PostgreSQL configurations for {mem_size_gb}GB")
            pg_configs = actions.pg_build_configs(mem_size_gb)
        else:
            print("Before: Using default PostgreSQL configurations")
            pg_configs = actions.pg_default_configs()
        self._write_pg_configs(
            mem_size_gb if self.pg_optimize_configs else None, pg_configs
        )
        actions.pg_apply_configs(
            self.suite.pg_admin_target,
            pg_configs,
            log=self.suite.log_config("before/log-01-configs"),
        )

        print("Before: Prepare commands")
        run.ssh_commands(
            self.suite.ssh_target,
            [
                "echo 'Restarting PostgreSQL cluster'",
                actions.cmd_pg_ctlcuster_restart(self.pg_version, self.pg_cluster_name),
                "echo 'Restarted.'",
                actions.CMD_DISABLE_SWAP,
                actions.CMD_SYNC,
                actions.CMD_DROP_CACHES,
            ],
            self.suite.log_config("before/log-02-script"),
        )

        print("Before: Reset psql stats")
        actions.pg_clear_stats(
            self.suite.pg_admin_target, log=self.suite.log_config("before/log-03-stats")
        )

        print("Before: Log /proc/vmstat")
        run.ssh_command(
            self.suite.ssh_target,
            "sudo cat /proc/vmstat",
            log=self.suite.log_config("before/vmstat"),
        )

        print("Before: Init PgStatLogger")
        self.pg_stat_logger = actions.PgStatLogger(
            self.suite.ssh_target, self.suite.pg_admin_target
        )
        self.pg_stat_logger.prepare()
        print("Before: Start PgStatLogger")
        self.pg_stat_logger.start()

        if self.page_evict_tracker is not None:
            print("Before: Init PageEvictTracker")
            self.page_evict_tracker.prepare()
            print("Before: Start PageEvictTracker")
            self.page_evict_tracker.start()

        if self.cache_ext_policy is not None:
            print("Before: Init CacheExtPolicy")
            self.cache_ext_policy.prepare()
            print("Before: Start CacheExtPolicy")
            self.cache_ext_policy.start()

        for bc in self.bpftrace_clients:
            print(f"Before: Preparing bpftrace client '{bc.config.name}'")
            bc.prepare(log=self.suite.log_config(f"before/bpftrace-{bc.config.name}"))
            print(f"Before: Running bpftrace script '{bc.config.name}'")
            bc.start()

    def _run_after(self) -> None:
        if self.pg_stat_logger is not None:
            self.pg_stat_logger.stop(self.suite.log_config("after/pg_stat_logger"))

        if self.page_evict_tracker is not None:
            print("After: Stop PageEvictTracker")
            self.page_evict_tracker.stop(
                self.suite.log_config("after/page_evict_tracker")
            )

        if self.cache_ext_policy is not None:
            print("After: Stop CacheExtPolicy")
            self.cache_ext_policy.stop(
                self.suite.log_config("after/cache_ext_policy")
            )

        if self.suite.pg_admin_target.log_folder is not None:
            print("After: Collecting PostgreSQL logs")
            log_folder = self.suite.pg_admin_target.log_folder
            actions.ssh_command(
                self.suite.ssh_target,
                f'sudo cat {log_folder}/"$(sudo ls -t {log_folder} | head -n1)"',
                log=self.suite.log_config("after/pg_logs"),
            )

        print("After: Log /proc/vmstat")
        run.ssh_command(
            self.suite.ssh_target,
            "sudo cat /proc/vmstat",
            log=self.suite.log_config("after/vmstat"),
        )

        print("After: Log psql stats")
        actions.pg_print_stats(
            self.suite.pg_admin_target, log=self.suite.log_config("after/stats")
        )

        print("After: List wait events")
        actions.pg_wait_events(
            self.suite.pg_admin_target, log=self.suite.log_config("after/wait-types")
        )

        print("After: Analyze waits")
        actions.pg_analyze_waits(
            self.suite.pg_admin_target, log=self.suite.log_config("after/wait-queries")
        )

        def _stop_and_cleanup(bc: BpftraceClient) -> None:
            print(f"After: Stopping bpftrace script '{bc.config.name}'")
            bc.stop(self.suite.log_config(f"bpftrace-{bc.config.name}"))
            print(f"After: Cleaning up bpftrace client '{bc.config.name}'")
            bc.cleanup()

        with ThreadPoolExecutor(
            max_workers=min(4, len(self.bpftrace_clients)) or 1
        ) as executor:
            futures = {
                executor.submit(_stop_and_cleanup, bc): bc
                for bc in self.bpftrace_clients
            }
            for future in as_completed(futures):
                bc = futures[future]
                exc = future.exception()
                if exc:
                    print(
                        f"After: Error stopping bpftrace client '{bc.config.name}': {exc}"
                    )

        print("After: Diff vmstat")
        vmstat.diff(
            self.suite.log_config("before/vmstat").log_file_path(),
            self.suite.log_config("after/vmstat").log_file_path(),
            log=self.suite.log_config("stats/vmstat"),
        )

    def _detect_memory_size(self) -> int:
        mem_size = actions.ssh_get_memory_size(self.suite.ssh_target)
        rounded_mem_size_gb = 2 ** math.ceil(math.log2(mem_size / 1024 / 1024))
        print(
            f"Run: Detected memory size {mem_size}KB, rounded to {rounded_mem_size_gb}GB"
        )
        return rounded_mem_size_gb

    def _write_pg_configs(
        self, mem_size_gb: Optional[int], pg_configs: Dict[str, str]
    ) -> None:
        file_path = self.suite.log_config("before/conf.sql").log_file_path()
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            if mem_size_gb is not None:
                f.write(f"-- Mem size: {mem_size_gb}GB\n")
            for k, v in pg_configs.items():
                f.write(f"ALTER SYSTEM SET {k} = '{v}';\n")
