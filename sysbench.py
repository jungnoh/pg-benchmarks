import pylib.suite as suite
from pylib.util import read_config_file
from pylib.target_run import shell_command


class SysbenchSuite(suite.Suite):
    def __init__(self, test_name: str, test_conf_file: str):
        super().__init__()
        self.test_name = test_name
        self.test_conf_args = self._read_test_conf(test_conf_file)
    
    def prepare(self):
        print("SysbenchSuite: Prepare")
    
    def run(self):
        print("SysbenchSuite: Run")
        cmd = self._build_command("run")
        shell_command(cmd, log=self.log_config("run"))
    
    def cleanup(self):
        print("SysbenchSuite: Cleanup")
    
    def _build_command(self, command: str):
        return [
            "sysbench",
            *self._build_pg_args(),
            self.test_name,
            *self.test_conf_args,
            command,
        ]
    
    def _read_test_conf(self, test_conf_file: str):
        args = []
        cfg = read_config_file(test_conf_file)
        for key, value in cfg.items():
            if value is None:
                args.append(f"--{key}")
            else:
                args.append(f"--{key}={value}")
        return args
    
    def _build_pg_args(self):
        args = [
            "--db-driver=pgsql",
            f"--pgsql-host={self.pg_runner_target.hostname}",
            f"--pgsql-port={self.pg_runner_target.port}",
            f"--pgsql-user={self.pg_runner_target.username}",
            f"--pgsql-db={self.pg_runner_target.database}",
        ]
        if self.pg_runner_target.password:
            args.append(f"--pgsql-password={self.pg_runner_target.password}")
        return args


if __name__ == "__main__":
    s = SysbenchSuite("oltp_read_write", "sysbench.conf")
    runner = suite.SuiteRunner("target.conf", s)
    runner.run()