from .util import read_config_file
from .target_run import PgTarget, LogConfig, shell_command
from typing import Optional
import subprocess


class HammerDBConfig(object):
    hammerdb_path: str
    use_stored_procs: bool
    tpcc_warehouse: int
    tpcc_vu: int
    tpcc_rampup: int
    tpcc_duration: int
    tpcc_all_warehouses: bool

    def read_config_file(config_file: str):
        config = read_config_file(config_file)
        result = HammerDBConfig()
        result.hammerdb_path = config.get("HAMMERDB_PATH", "/opt/HammerDB-5.0")
        result.use_stored_procs = config.get("USE_STORED_PROCS", "true")
        result.tpcc_warehouse = config.get("TPCC_WAREHOUSE", "10")
        result.tpcc_vu = config.get("TPCC_VU", "4")
        result.tpcc_rampup = config.get("TPCC_RAMPUP", "2")
        result.tpcc_duration = config.get("TPCC_DURATION", "5")
        result.tpcc_all_warehouses = config.get("TPCC_ALL_WAREHOUSES", "false")
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
            f"diset tpcc pg_timeprofile true",
            f"diset tpcc pg_allwarehouse {self.config.tpcc_all_warehouses}",
            "loadscript",
            f"vuset vu {self.config.tpcc_vu}",
            "vuset logtotemp 1",
            "vuset unique 1",
            "vuset showoutput 1",
            "tcset refreshrate 10",
            "tcset logtotemp 1",
            "tcset timestamps 1",
            'puts "Creating virtual users..."',
            "vucreate",
            'puts "Starting transaction counter..."',
            "tcstart",
            'puts "Starting TPC-C run..."',
            "set jobid [ vurun ]",
            "set jobid [ split $jobid '=' ]",
            "set jobid [ lindex $jobid 1 ]",
            'puts "Job ID: $jobid"',
            'puts "Stopping transaction counter..."',
            "tcstop",
            'puts "=== Latency Percentiles ==="',
            "jobs $jobid timing",
            'puts "=== END ==="',
            'puts "=== Transaction Counter Status ==="',
            "tcstatus",
            'puts "=== END ==="',
            'puts "Cleaning up..."',
            "vudestroy",
            "after 5000",
        ]

    def build_cleanup_script(self):
        return [
            *self.build_common_script(),
            'puts "Dropping TPC-C schema..."',
            "deleteschema",
            'puts "Schema dropped."',
        ]

    def build_common_script(self):
        return [
            "dbset db pg",
            "dbset bm TPC-C",
            # Connection
            f"diset connection pg_host {self.pg_admin_target.hostname}",
            f"diset connection pg_port {self.pg_admin_target.port}",
            # Credentials
            f"diset tpcc pg_superuser {self.pg_admin_target.username}",
            f"diset tpcc pg_superuserpass {self.pg_admin_target.password}",
            f"diset tpcc pg_defaultdbase {self.pg_admin_target.database}",
            f"diset tpcc pg_user {self.pg_runner_target.username}",
            f"diset tpcc pg_pass {self.pg_runner_target.password}",
            f"diset tpcc pg_dbase {self.pg_runner_target.database}",
            # TPC-C settings
            f"diset tpcc pg_count_ware {self.config.tpcc_warehouse}",
            f"diset tpcc pg_num_vu {self.config.tpcc_vu}",
            f"diset tpcc pg_storedprocs {self.config.use_stored_procs}",
        ]


def run_script(
    config: HammerDBConfig, script_path: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    result = shell_command(
        f"./hammerdbcli auto {script_path}", log=log, cwd=config.hammerdb_path
    )
    return result
