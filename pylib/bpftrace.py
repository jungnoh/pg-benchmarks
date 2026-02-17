import paramiko
from dataclasses import dataclass
from .target_run import SshTarget, LogConfig, ssh_copy_file
from typing import Optional, Dict
import time
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent / "bpftrace-scripts"


@dataclass
class BpftraceConfig:
    def pg_page_intervals(config: Dict[str, str]) -> 'BpftraceConfig':
        script_path = SCRIPT_DIR / "pg_page_intervals.bt"
        parse_script = SCRIPT_DIR / "pg_page_intervals_parse.py"
        cfg = BpftraceConfig(
            name="pg_page_intervals",
            script_path=script_path,
            parse_script=parse_script,
            bpftrace_additional_args="$(id -u postgres)",
        )
        return cfg._apply_config(config)

    def _apply_config(self, config: Dict[str, str]):
        if "BPFTRACE_PATH" in config:
            self.bpftrace_path = config["BPFTRACE_PATH"]
        if "CLEANUP_TIMEOUT" in config:
            self.cleanup_timeout = int(config["CLEANUP_TIMEOUT"])
        return self

    name: str
    script_path: str
    parse_script: Optional[str] = None
    bpftrace_path: str = "/home/jungnoh/bpftrace"
    bpftrace_additional_args: str = ""
    cleanup_timeout: int = 300


class BpftraceClient:

    def __init__(self, target: SshTarget, config: BpftraceConfig):
        self.target = target
        self.config = config
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.remote_trace_pid = None

    def prepare(self, log: Optional[LogConfig] = None):
        print("Sending bpftrace script to the target")
        ssh_copy_file(
            self.target, self.config.script_path, self.remote_script_path, log
        )
        if self.config.parse_script is not None:
            print("Sending bpftrace parse script to the target")
            ssh_copy_file(
                self.target,
                self.config.parse_script,
                self.remote_parse_script_path,
                log,
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
        bpftrace_cmd = (
            f"sudo bash -c 'BPFTRACE_MAX_MAP_KEYS=9999999 nohup {self.config.bpftrace_path} {self.remote_script_path} {self.config.bpftrace_additional_args} "
            + "> /tmp/probe.out 2>&1 & echo $!'"
        )
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
        # Wait for script to finish
        WAIT_COUNT = int(self.config.cleanup_timeout / 0.5)
        for i in range(WAIT_COUNT):
            # Check if the script is still running
            _, stdout, _ = self.ssh.exec_command(f"ps -p {self.remote_trace_pid}")
            if f"{self.remote_trace_pid}" not in stdout.read().decode():
                print(f"Bpftrace script stopped with PID: {self.remote_trace_pid}")
                break
            if i == WAIT_COUNT - 1:
                print(f"Bpftrace script did not stop with PID: {self.remote_trace_pid}")
                break
            time.sleep(0.5)
        self.remote_trace_pid = None

        if self.config.parse_script is None:
            _, stdout, _ = self.ssh.exec_command("cat /tmp/probe.out")
            raw = stdout.read().decode()
            return raw
        else:
            print("Running bpftrace parse script")
            _, stdout, _ = self.ssh.exec_command(
                f"{self.remote_parse_script_path} /tmp/probe.out"
            )
            raw = stdout.read().decode()
            return raw

    def cleanup(self):
        self.ssh.close()
    
    @property
    def remote_script_path(self) -> str:
        return f"/tmp/{self.config.name}.bt"
    
    @property
    def remote_parse_script_path(self) -> str:
        return f"/tmp/{self.config.name}_parse.py"
