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
            database=self.config["PG_ADMIN_DATABASE"]
        )
        self.suite.pg_runner_target = PgTarget(
            username=self.config["PG_RUNNER_USERNAME"],
            password=self.config["PG_RUNNER_PASSWORD"],
            hostname=self.config["PG_RUNNER_HOST"],
            port=self.config["PG_RUNNER_PORT"],
            database=self.config["PG_RUNNER_DATABASE"]
        )
        self.suite.ssh_target = SshTarget(
            username=self.config["SSH_USERNAME"],
            password=self.config["SSH_PASSWORD"],
            hostname=self.config["SSH_HOST"],
            port=self.config["SSH_PORT"]
        )
    
    def run(self) -> None:
        self._run_before()
        self.suite.run()
        self._run_after()
    
    def _run_before(self) -> None:
        mem_size_gb = self._detect_memory_size()
        print(f"Before: Applying PostgreSQL configurations for {mem_size_gb}GB")
        pg_configs = actions.pg_build_configs(mem_size_gb)
        self._write_pg_configs(mem_size_gb, pg_configs)
        actions.pg_apply_configs(self.suite.pg_admin_target, pg_configs, log=self.suite.log_config("before/log-01-configs"))

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
        actions.pg_clear_stats(self.suite.pg_admin_target, log=self.suite.log_config("before/log-03-stats"))

        print("Before: Log /proc/vmstat")
        run.ssh_command(self.suite.ssh_target, "sudo cat /proc/vmstat", log=self.suite.log_config("before/vmstat"))
    
    def _run_after(self) -> None:
        print("After: Log /proc/vmstat")
        run.ssh_command(self.suite.ssh_target, "sudo cat /proc/vmstat", log=self.suite.log_config("after/vmstat"))

        print("After: Log psql stats")
        actions.pg_print_stats(self.suite.pg_admin_target, log=self.suite.log_config("after/stats"))

        print("After: Analyze waits")
        actions.pg_analyze_waits(self.suite.pg_admin_target, log=self.suite.log_config("after/waits"))

        print("After: Diff vmstat")
        vmstat.diff(
            self.suite.log_config("before/vmstat").log_file_path(),
            self.suite.log_config("after/vmstat").log_file_path(),
            log=self.suite.log_config("stats/vmstat")
        )
    
    def _detect_memory_size(self) -> int:
        mem_size = actions.ssh_get_memory_size(self.suite.ssh_target)
        rounded_mem_size_gb = 2 ** math.ceil(math.log2(mem_size / 1024 / 1024))
        print(f"Run: Detected memory size {mem_size}KB, rounded to {rounded_mem_size_gb}GB")
        return rounded_mem_size_gb
    
    def _write_pg_configs(self, mem_size_gb: int, pg_configs: Dict[str, str]) -> None:
        file_path = self.suite.log_config("before/conf.sql").log_file_path()
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(f"-- Mem size: {mem_size_gb}GB\n")
            for k, v in pg_configs.items():
                f.write(f"ALTER SYSTEM SET {k} = '{v}';\n")
