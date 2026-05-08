import subprocess
from typing import Optional

from .target_run import LogConfig, PgTarget, shell_command
from .util import read_config_file


class HammerDBConfig(object):
    hammerdb_path: str
    hammerdb_benchmark: str
    use_stored_procs: bool
    tpcc_warehouse: int
    tpcc_vu: int
    tpcc_rampup: int
    tpcc_duration: int
    tpcc_all_warehouses: bool
    tpch_parallelism: int
    tpch_scale_factor: int
    tpch_threads: int

    @staticmethod
    def read_config_file(config_file: str):
        config = read_config_file(config_file)
        result = HammerDBConfig()
        result.hammerdb_path = config.get("HAMMERDB_PATH") or "/opt/HammerDB-5.0"
        result.hammerdb_benchmark = (
            config.get("HAMMERDB_BENCHMARK") or "tpc-c"
        ).lower()
        if result.hammerdb_benchmark not in ["tpc-c", "tpc-h"]:
            raise ValueError(f"Invalid benchmark type {result.hammerdb_benchmark}")

        result.tpch_parallelism = int(config.get("TPCH_PARALLELISM") or "4")
        result.tpch_scale_factor = int(config.get("TPCH_SCALE_FACTOR") or "10")
        result.tpch_threads = int(config.get("TPCH_THREADS") or "16")
        result.tpcc_warehouse = int(config.get("TPCC_WAREHOUSE") or "10")
        result.tpcc_vu = int(config.get("TPCC_VU") or "4")
        result.tpcc_rampup = int(config.get("TPCC_RAMPUP") or "2")
        result.tpcc_duration = int(config.get("TPCC_DURATION") or "5")
        result.tpcc_all_warehouses = (
            config.get("TPCC_ALL_WAREHOUSES") or "false"
        ).lower() == "true"
        result.use_stored_procs = (
            config.get("USE_STORED_PROCS") or "true"
        ).lower() == "true"
        return result


class ScriptBuilder(object):
    def __init__(
        self,
        pg_admin_target: PgTarget,
        pg_runner_target: PgTarget,
        config: HammerDBConfig,
    ):
        self.pg_admin_target = pg_admin_target
        self.pg_runner_target = pg_runner_target
        self.config = config

    def write_schema_script(self, dest_file: str):
        with open(dest_file, "w") as f:
            f.write("\n".join(self.build_schema_script()))

    def write_run_script(self, dest_file: str):
        with open(dest_file, "w") as f:
            f.write("\n".join(self.build_run_script()))

    def write_cleanup_script(self, dest_file: str):
        with open(dest_file, "w") as f:
            f.write("\n".join(self.build_cleanup_script()))

    def build_schema_script(self):
        return [
            *self.build_common_script(),
            'puts "Starting schema build..."',
            'puts "This may take several minutes depending on warehouse count."',
            "buildschema",
        ]

    def build_run_script(self):
        return [
            *self.build_common_script(),
            f"diset tpcc pg_rampup {self.config.tpcc_rampup}",
            f"diset tpcc pg_duration {self.config.tpcc_duration}",
            "diset tpcc pg_timeprofile true",
            f"diset tpcc pg_allwarehouse {self.config.tpcc_all_warehouses}",
            "loadscript",
            f"vuset vu {self.config.tpcc_vu}",
            "vuset logtotemp 1",
            "vuset unique 1",
            "vuset showoutput 1",
            "tcset refreshrate 1",
            "tcset logtotemp 1",
            "tcset timestamps 1",
            'puts "Creating virtual users..."',
            "vucreate",
            'puts "Starting transaction counter..."',
            "tcstart",
            f'puts "Starting {self.config.hammerdb_benchmark.upper()} run..."',
            "set jobid [ vurun ]",
            "set jobid [ split $jobid '=' ]",
            "set jobid [ lindex $jobid 1 ]",
            'puts "Job ID: $jobid"',
            'puts "Stopping transaction counter..."',
            "tcstop",
            'puts "=== END ==="',
            'puts "Cleaning up..."',
            "vudestroy",
            "after 5000",
        ]

    def build_cleanup_script(self):
        return [
            *self.build_common_script(),
            f'puts "Dropping {self.config.hammerdb_benchmark.upper()} schema..."',
            "deleteschema",
            'puts "Schema dropped."',
        ]

    def build_common_script(self):
        key = {"tpc-c": "tpcc", "tpc-h": "tpch"}[self.config.hammerdb_benchmark]
        script = [
            "dbset db pg",
            f"dbset bm {self.config.hammerdb_benchmark.upper()}",
            # Connection
            f"diset connection pg_host {self.pg_admin_target.hostname}",
            f"diset connection pg_port {self.pg_admin_target.port}",
        ]
        if self.config.hammerdb_benchmark == "tpc-c":
            script.extend(
                [
                    # Credentials
                    f"diset tpcc pg_superuser {self.pg_admin_target.username}",
                    f"diset tpcc pg_superuserpass {self.pg_admin_target.password}",
                    f"diset tpcc pg_defaultdbase {self.pg_admin_target.database}",
                    f"diset tpcc pg_user {self.pg_runner_target.username}",
                    f"diset tpcc pg_pass {self.pg_runner_target.password}",
                    f"diset tpcc pg_dbase {self.pg_runner_target.database}",
                    # Scale
                    f"diset tpcc pg_count_ware {self.config.tpcc_warehouse}",
                    f"diset tpcc pg_num_vu {self.config.tpcc_vu}",
                    f"diset tpcc pg_storedprocs {self.config.use_stored_procs}",
                ]
            )
        elif self.config.hammerdb_benchmark == "tpc-h":
            script.extend(
                [
                    # Credentials
                    f"diset tpch pg_tpch_superuser {self.pg_admin_target.username}",
                    f"diset tpch pg_tpch_superuserpass {self.pg_admin_target.password}",
                    f"diset tpch pg_tpch_defaultdbase {self.pg_admin_target.database}",
                    f"diset tpch pg_tpch_user {self.pg_runner_target.username}",
                    f"diset tpch pg_tpch_pass {self.pg_runner_target.password}",
                    f"diset tpch pg_tpch_dbase {self.pg_runner_target.database}",
                    # Scale
                    f"diset tpch pg_degree_of_parallel {self.config.tpch_parallelism}",
                    f"diset tpch pg_scale_fact {self.config.tpch_scale_factor}",
                    f"diset tpch pg_num_tpch_threads {self.config.tpch_threads}",
                ]
            )

        return script


def run_script(
    config: HammerDBConfig, script_path: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    result = shell_command(
        f"./hammerdbcli auto {script_path}", log=log, cwd=config.hammerdb_path
    )
    return result
