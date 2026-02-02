import paramiko
from dataclasses import dataclass
from .target_run import SshTarget, LogConfig, ssh_copy_file
from typing import Optional
import time


@dataclass
class BpftraceConfig:
    bpftrace_path: str = "/home/jungnoh/bpftrace"
    bpftrace_additional_args: str = ""
    script_path: str = "pg_bpftrace.bt"


class BpftraceClient:
    _REMOTE_SCRIPT_PATH: str = "/tmp/pg_trace.bt"

    def __init__(self, target: SshTarget, config: BpftraceConfig):
        self.target = target
        self.config = config
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.remote_trace_pid = None

    def prepare(self, log: Optional[LogConfig] = None):
        print("Sending bpftrace script to the target")
        ssh_copy_file(
            self.target, self.config.script_path, self._REMOTE_SCRIPT_PATH, log
        )
        print("Connecting to the target")
        self.ssh.connect(
            self.target.hostname,
            port=self.target.port,
            username=self.target.username,
            password=self.target.password,
        )
        print("Connected to the target")

    def start(self) -> int:
        bpftrace_cmd = f"sudo bash -c 'BPFTRACE_MAX_MAP_KEYS=131072 nohup sudo {self.config.bpftrace_path} {self._REMOTE_SCRIPT_PATH} {self.config.bpftrace_additional_args} " + \
            "> /tmp/probe.out 2>&1 & echo $!'"
        print(f"Running bpftrace command: {bpftrace_cmd}")
        _, stdout, _ = self.ssh.exec_command(bpftrace_cmd)
        pid = int(stdout.read().decode().strip())
        print(f"Bpftrace script started with PID: {pid}")
        self.remote_trace_pid = pid
        time.sleep(2)  # let probes attach

    def stop(self) -> str:
        if self.remote_trace_pid is None:
            print("No bpftrace script is running")
            return
        self.ssh.exec_command(f"sudo kill -INT {self.remote_trace_pid}")
        time.sleep(5)  # wait for the script to finish
        print(f"Bpftrace script stopped with PID: {self.remote_trace_pid}")
        self.remote_trace_pid = None

        _, stdout, _ = self.ssh.exec_command("cat /tmp/probe.out")
        raw = stdout.read().decode()
        return raw

    def cleanup(self):
        self.ssh.close()
