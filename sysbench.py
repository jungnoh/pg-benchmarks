import pylib.suite as suite
import sys
from typing import List
from pylib.util import read_config_file
from pylib.target_run import shell_command, LogConfig, PgTarget


class SysbenchSuite(suite.Suite):
    def __init__(self, test_name: str, test_conf_file: str):
        super().__init__()
        self.test_name = test_name
        self.test_conf_args = _build_args_from_test_conf(test_conf_file)

    def log_config(self, action: str) -> LogConfig:
        return LogConfig(
            run_id=f"sysbench-{self.test_name}/{self.start_time:.0f}", action=action
        )

    def prepare(self):
        shell_command(self._build_command("prepare"))

    def run(self):
        cmd = self._build_command("run")
        self._write_cmd_to_log(cmd)
        shell_command(cmd, log=self.log_config("run"))

    def cleanup(self):
        shell_command(self._build_command("cleanup"))

    def _build_command(self, command: str):
        return [
            "sysbench",
            *_build_sysbench_args(self.pg_runner_target),
            self.test_name,
            *self.test_conf_args,
            command,
        ]

    def _write_cmd_to_log(self, cmd: List[str]):
        self.log_config("command").ensure_log_folder()
        with open(self.log_config("command").log_file_path(), "w") as f:
            f.write("\n  ".join(cmd))


def _build_args_from_test_conf(test_conf_file: str) -> List[str]:
    args = []
    cfg = read_config_file(test_conf_file)
    for key, value in cfg.items():
        if value is None:
            args.append(f"--{key}")
        else:
            args.append(f"--{key}={value}")
    return args


def _build_sysbench_args(target: PgTarget) -> List[str]:
    args = [
        "--db-driver=pgsql",
        f"--pgsql-host={target.hostname}",
        f"--pgsql-port={target.port}",
        f"--pgsql-user={target.username}",
        f"--pgsql-db={target.database}",
    ]
    if target.password:
        args.append(f"--pgsql-password={target.password}")
    return args


if __name__ == "__main__":
    overrides, argv = suite.parse_cli_overrides(sys.argv)
    if len(argv) < 2:
        sys.exit(f"Usage: {argv[0]} <prepare|run|cleanup>")

    s = SysbenchSuite("oltp_read_write", "sysbench.conf")
    runner = suite.SuiteRunner("target.conf", s, config_overrides=overrides)
    runner.vm_controller.ensure_running(s.ssh_target, s.pg_admin_target)

    command = argv[1]
    if command == "prepare":
        s.prepare()
    elif command == "run":
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
    elif command == "cleanup":
        s.cleanup()
    else:
        sys.exit(f"Usage: {argv[0]} <prepare|run|cleanup>")
