import os
import sys

import pylib.suite as suite
from pylib.hammerdb import HammerDBConfig, ScriptBuilder, run_script
from pylib.target_run import LogConfig


class HammerDBSuite(suite.Suite):
    name_prefix = ""

    def __init__(self, config_file: str):
        super().__init__()
        self.config = HammerDBConfig.read_config_file(config_file)

    def log_config(self, action: str) -> LogConfig:
        if self.name_prefix == "":
            return LogConfig(run_id=f"hammerdb/{self.start_time:.0f}", action=action)
        else:
            return LogConfig(
                run_id=f"hammerdb/{self.name_prefix}-{self.start_time:.0f}",
                action=action,
            )

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
    overrides, argv = suite.parse_cli_overrides(sys.argv)
    if len(argv) < 2:
        sys.exit(f"Usage: {argv[0]} <prepare|run|cleanup>")

    s = HammerDBSuite("hammerdb.conf")
    runner = suite.SuiteRunner("target.conf", s, config_overrides=overrides)

    command = argv[1]
    if command == "prepare":
        s.prepare()
    elif command == "run":
        if len(argv) >= 3:
            s.name_prefix = argv[2]
        runner.run()
    elif command == "cleanup":
        s.cleanup()
    else:
        sys.exit(f"Usage: {argv[0]} <prepare|run|cleanup>")
