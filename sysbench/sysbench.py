#!/usr/bin/env python3
import subprocess
import sys
import time
import os
from typing import List
import read_vmstat

CONFIG_FILE = "sysbench.cfg"
TEST_CONFIG_FILE = "test.cfg"

SSH_HOST = "localhost"
SSH_USER = "jungnoh"
SSH_PORT = "5555"

def parse_config(path):
    args = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                if value:
                    args.append(f"--{key.strip()}={value.strip()}")
                else:
                    args.append(f"--{key.strip()}")
    return args


def run(cmd, log_file=None):
    if log_file:
        subprocess.run(f"mkdir -p {os.path.dirname(log_file)}", shell=True, check=True)
        subprocess.run(f"{' '.join(cmd)} 2>&1 | tee -a {log_file}", shell=True, check=True)
        
    else:
        subprocess.run(' '.join(cmd), shell=True, check=True)


class SysbenchTask(object):
    testname: str
    log_key: str

    BEFORE_RUN_CMDS = [
        "echo 'Restarting postgresql'",
        "sudo pg_ctlcluster 18 main restart",
        "echo 'Restarted.'",
        "sudo swapoff -a",
        "sudo sync",
        "sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'",
        "echo 'Resetting psql stats'",
        "cd / && sudo -u postgres psql -c 'SELECT pg_stat_statements_reset();'",
        "cd / && sudo -u postgres psql -c 'SELECT pg_stat_kcache_reset();'",
        "cd / && sudo -u postgres psql -c 'SELECT pg_wait_sampling_reset_profile();'",
        "cd / && sudo -u postgres psql -c 'SELECT pg_stat_reset();'",
        "echo '======= CPU Info ==========='",
        "lscpu",
        "echo '======= Memory Info ========'",
        "free -h",
        "echo '======= vmstat ============='",
        "sudo cat /proc/vmstat"
    ]

    AFTER_RUN_CMDS = [
        "echo '======= vmstat ============='",
        "sudo cat /proc/vmstat",
        "echo '======= pg_stat_bgwriter ==='",
        "cd / && sudo -u postgres psql -d sbtest -c 'SELECT * FROM pg_stat_bgwriter;'",
        "echo '======= pg_stat_io ========='",
        "cd / && sudo -u postgres psql -d sbtest -c 'SELECT * FROM pg_stat_io;'",
        "echo '======= pg_stat_wal ========'",
        "cd / && sudo -u postgres psql -d sbtest -c 'SELECT * FROM pg_stat_wal;'",
    ]

    def __init__(self, testname: str):
        self.testname = testname
        self.log_key = testname + "/" + str(int(time.time()))

    def prepare(self):
        self._sysbench("prepare", [])
    
    def run(self, mem_size_gb: int):
        self._prepare_log_folder()
        self._setup_pg_configs(mem_size_gb)
        self._run_commands("before_run", self.BEFORE_RUN_CMDS)
        self._sysbench("run", [], log_key=self.log_key)
        self._run_commands("after_run", self.AFTER_RUN_CMDS)
        read_vmstat.run(os.path.join("logs", self.log_key))
        self._run_sql("analyze_waits.sql", log_file=log_file_name(self.log_key, "analyze_waits"))
    
    def cleanup(self):
        self._sysbench("cleanup", [])

    def _setup_pg_configs(self, mem_size_gb: int):
        pg_configs = self._make_pg_configs(mem_size_gb)
        pg_config_file = os.path.join("logs", self.log_key, "conf.sql")
        with open(pg_config_file, "w") as f:
            f.write(f"-- Mem size: {mem_size_gb}GB\n")
            for k, v in pg_configs.items():
                f.write(f"ALTER SYSTEM SET {k} = '{v}';\n")
        self._run_sql(pg_config_file, log_file=log_file_name(self.log_key, "pg_conf_apply"))

    def _make_pg_configs(self, mem_size_gb: int):
        # https://github.com/le0pard/pgtune/blob/master/src/features/configuration/configurationSlice.js
        mem_mb = mem_size_gb * 1024
        return {
            "shared_buffers": f"{(mem_mb * 0.25):.0f}MB",
            "effective_cache_size": f"{(mem_mb * 0.75):.0f}MB",
            "maintenance_work_mem": f"{(mem_mb / 16):.0f}MB",
            "random_page_cost": "1.1",
            "checkpoint_completion_target": "0.9",
            "effective_io_concurrency": "200",
        }

    def _sysbench(self, command: str, args: List[str], log_key=None):
        test_args = parse_config(TEST_CONFIG_FILE)
        log_file = None
        if log_key:
            log_file = log_file_name(log_key, command)
        run(["sysbench", f"--config-file={CONFIG_FILE}", self.testname, *test_args, command], log_file=log_file)
    
    def _prepare_log_folder(self):
        subprocess.run(f"mkdir -p logs/{self.log_key}", shell=True, check=True)
        subprocess.run(f"cp {CONFIG_FILE} logs/{self.log_key}/sysbench.cfg", shell=True, check=True)
        subprocess.run(f"cp {TEST_CONFIG_FILE} logs/{self.log_key}/test.cfg", shell=True, check=True)

    def _run_commands(self, run_command: str, commands: List[str]):
        cmd = ["ssh", "-p", SSH_PORT, f"{SSH_USER}@{SSH_HOST}", '"' + " && ".join(commands) + '"'];
        run(cmd, log_file_name(self.log_key, run_command))
    
    def _run_sql(self, filename: str, log_file=None):
        os.environ["PGPASSWORD"] = "postgres"
        run(["psql", "-U", "postgres", "-h", "127.0.0.1", "-p", "35432", "-f", filename], log_file=log_file)



def log_file_name(key: str, action: str):
    return f"logs/{key}/{action}.log"

def sysbench(task: str, command: str, args: List[str], log_key=None):
    test_args = parse_config(TEST_CONFIG_FILE)
    run(["sysbench", f"--config-file={CONFIG_FILE}", task, *test_args, *args, command], **kwargs)

def sysbench_prepare(task: str, *args):
    sysbench(task, "prepare", *args)

def sysbench_run(task: str, *args):
    KEY = task + "/" + str(int(time.time()))
    print(f"Log key: {KEY}")
    subprocess.run(f"mkdir -p logs/{KEY}", shell=True, check=True)
    subprocess.run(f"cp {CONFIG_FILE} logs/{KEY}/sysbench.cfg", shell=True, check=True)
    subprocess.run(f"cp {TEST_CONFIG_FILE} logs/{KEY}/test.cfg", shell=True, check=True)

    sysbench(task, "run", *args, log_key=key)

def sysbench_cleanup(task: str, *args):
    sysbench(task, "cleanup", *args)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(f"Usage: {sys.argv[0]} <task> <command> [args...]")

    task = sys.argv[1]
    command = sys.argv[2]
    args = sys.argv[3:]
    task = SysbenchTask(task)

    if command == "prepare":
        task.prepare()
    elif command == "run":
        if len(args) < 1:
            sys.exit(f"Usage: {sys.argv[0]} <task> <command> <mem_size_gb> [args...]")
        mem_size_gb = int(args[0])
        args = args[1:]
        task.run(mem_size_gb)
    elif command == "cleanup":
        task.cleanup()
    else:
        sys.exit(f"Unknown command: {command}")