from abc import ABC, abstractmethod
import time
import math
from pathlib import Path
from typing import Dict
from .target_run import SshTarget, PgTarget, LogConfig
from .util import read_config_file
from . import target_actions as actions
from . import target_run as run
from . import vmstat
from .bpftrace import BpftraceClient, BpftraceConfig
from typing import Optional


def config_to_bool(config: Dict[str, str], key: str, default: bool = False) -> bool:
    value = config.get(key, default)
    if value.lower() in ["true", "yes", "1"]:
        return True
    elif value.lower() in ["false", "no", "0"]:
        return False
    else:
        raise ValueError(f"Invalid boolean value: {value}")


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

    def log_config(self, action: str) -> LogConfig:
        return LogConfig(run_id=f"{self.start_time:.0f}", action=action)


class SuiteRunner(ABC):
    bpftrace_client: Optional[BpftraceClient] = None

    def __init__(self, config_file: str, suite: Suite):
        self.config = read_config_file(config_file)
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
        if "BPFTRACE_SCRIPT" in self.config:
            bpftrace_script = self.config["BPFTRACE_SCRIPT"]
            # Check if file exists
            if not Path(bpftrace_script).exists():
                raise FileNotFoundError(
                    f"BPFTRACE_SCRIPT file not found: {bpftrace_script}"
                )
            bpftrace_config = BpftraceConfig(script_path=bpftrace_script)
            if "BPFTRACE_PATH" in self.config:
                bpftrace_config.bpftrace_path = self.config["BPFTRACE_PATH"]
            if "BPFTRACE_ADDITIONAL_ARGS" in self.config:
                bpftrace_config.bpftrace_additional_args = self.config[
                    "BPFTRACE_ADDITIONAL_ARGS"
                ]
            self.bpftrace_client = BpftraceClient(
                self.suite.ssh_target, bpftrace_config
            )
        else:
            self.bpftrace_client = None

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
        self._write_pg_configs(mem_size_gb, pg_configs)
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

        if self.bpftrace_script is not None:
            print(f"Before: Preparing bpftrace client")
            self.bpftrace_client.prepare(log=self.suite.log_config("before/bpftrace"))
            print(f"Before: Running bpftrace script: {self.bpftrace_script}")
            self.bpftrace_client.start()

    def _run_after(self) -> None:
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

        print("After: Analyze waits")
        actions.pg_analyze_waits(
            self.suite.pg_admin_target, log=self.suite.log_config("after/waits")
        )

        if self.bpftrace_client is not None:
            print(f"After: Stopping bpftrace script")
            raw = self.bpftrace_client.stop()
            print(f"After: Writing bpftrace output to file")
            with open(
                self.suite.log_config("after/bpftrace").log_file_path(), "w"
            ) as f:
                f.write(raw)
            print(f"After: Cleaning up bpftrace client")
            self.bpftrace_client.cleanup()

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

    def _write_pg_configs(self, mem_size_gb: int, pg_configs: Dict[str, str]) -> None:
        file_path = self.suite.log_config("before/conf.sql").log_file_path()
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(f"-- Mem size: {mem_size_gb}GB\n")
            for k, v in pg_configs.items():
                f.write(f"ALTER SYSTEM SET {k} = '{v}';\n")
