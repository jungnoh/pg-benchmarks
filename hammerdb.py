import argparse
import os
import sys
from typing import Optional

import pylib.suite as suite
from pylib.hammerdb import HammerDBConfig, ScriptBuilder, run_script
from pylib.target_run import LogConfig


class HammerDBSuite(suite.Suite):
    name_prefix = ""
    sample_id: Optional[str] = None

    def __init__(self, config_file: str):
        super().__init__()
        self.config = HammerDBConfig.read_config_file(config_file)

    def run_id_suffix(self) -> str:
        if self.sample_id:
            return f"{self.start_time:.0f}-{self.sample_id}"
        return f"{self.start_time:.0f}"

    def log_config(self, action: str) -> LogConfig:
        suffix = self.run_id_suffix()
        if self.name_prefix == "":
            return LogConfig(run_id=f"hammerdb/{suffix}", action=action)
        return LogConfig(
            run_id=f"hammerdb/{self.name_prefix}-{suffix}", action=action
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

    parser = argparse.ArgumentParser(prog=argv[0])
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("name", nargs="?", default="")
    run_parser.add_argument("--samples", type=int, default=1)
    subparsers.add_parser("cleanup")

    args = parser.parse_args(argv[1:])

    if args.command == "prepare":
        s = HammerDBSuite("hammerdb.conf")
        runner = suite.SuiteRunner("target.conf", s, config_overrides=overrides)
        runner.vm_controller.ensure_running(s.ssh_target, s.pg_admin_target)
        s.prepare()
    elif args.command == "cleanup":
        s = HammerDBSuite("hammerdb.conf")
        runner = suite.SuiteRunner("target.conf", s, config_overrides=overrides)
        runner.vm_controller.ensure_running(s.ssh_target, s.pg_admin_target)
        s.cleanup()
    elif args.command == "run":
        if args.samples < 1:
            run_parser.error("--samples must be >= 1")
        if args.samples > 1 and not args.name:
            run_parser.error("--samples > 1 requires a run name")

        if args.samples == 1:
            s = HammerDBSuite("hammerdb.conf")
            if args.name:
                s.name_prefix = args.name
            runner = suite.SuiteRunner(
                "target.conf", s, config_overrides=overrides
            )
            runner.vm_controller.ensure_running(s.ssh_target, s.pg_admin_target)
            runner.run()
            if suite.cache_ext_policy_timed_out(runner):
                print(
                    "cache-ext policy did not exit cleanly; "
                    "recovering VM before exiting"
                )
                suite.recover_vm(
                    runner.vm_controller,
                    runner.suite.ssh_target,
                    runner.suite.pg_admin_target,
                )
        else:
            for i in range(1, args.samples + 1):
                print(f"=== Sample {i}/{args.samples} ===")
                s = HammerDBSuite("hammerdb.conf")
                s.name_prefix = args.name
                s.sample_id = f"sample{i:02d}"
                runner = suite.SuiteRunner(
                    "target.conf", s, config_overrides=overrides
                )
                runner.vm_controller.ensure_running(
                    s.ssh_target, s.pg_admin_target
                )
                runner.run()
                if suite.cache_ext_policy_timed_out(runner):
                    print(
                        f"cache-ext policy did not exit cleanly after "
                        f"sample {i}; recovering VM before continuing"
                    )
                    suite.recover_vm(
                        runner.vm_controller,
                        runner.suite.ssh_target,
                        runner.suite.pg_admin_target,
                    )
