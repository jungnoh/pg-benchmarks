from pylib.hammerdb import HammerDBConfig, ScriptBuilder, run_script
from pylib.target_run import LogConfig
import pylib.suite as suite
import os
import sys


class HammerDBSuite(suite.Suite):
    def __init__(self, config_file: str):
        super().__init__()
        self.config = HammerDBConfig.read_config_file(config_file)

    def log_config(self, action: str) -> LogConfig:
        return LogConfig(run_id=f"hammerdb/{self.start_time:.0f}", action=action)

    def prepare(self):
        os.makedirs("hammerdb-scripts", exist_ok=True)
        script_path = "hammerdb-scripts/setup.tcl"
        self._script_builder().write_schema_script(script_path)
        run_script(self.config, os.path.abspath(script_path))

    def run(self):
        os.makedirs("hammerdb-scripts", exist_ok=True)
        script_path = "hammerdb-scripts/run.tcl"
        self._script_builder().write_run_script(script_path)

        with open(script_path, "r") as f:
            script = f.read()
            with open(self.log_config("script.tcl").log_file_path(), "a") as f:
                f.write(script)

        run_script(
            self.config, os.path.abspath(script_path), log=self.log_config("run")
        )

    def cleanup(self):
        os.makedirs("hammerdb-scripts", exist_ok=True)
        script_path = "hammerdb-scripts/cleanup.tcl"
        self._script_builder().write_cleanup_script(script_path)
        run_script(self.config, os.path.abspath(script_path))

    def _script_builder(self):
        return ScriptBuilder(self.pg_admin_target, self.pg_runner_target, self.config)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"Usage: {sys.argv[0]} <prepare|run|cleanup>")

    s = HammerDBSuite("hammerdb.conf")
    runner = suite.SuiteRunner("target.conf", s)

    command = sys.argv[1]
    if command == "prepare":
        s.prepare()
    elif command == "run":
        runner.run()
    elif command == "cleanup":
        s.cleanup()
    else:
        sys.exit(f"Usage: {sys.argv[0]} <prepare|run|cleanup>")
