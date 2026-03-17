import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import paramiko

from .target_run import LogConfig, SshTarget, ssh_copy_file, ssh_retrieve_file

SCRIPT_DIR = Path(__file__).parent / "bpftrace-scripts"


@dataclass
class BpftraceParseScript:
    script_path: str
    output_path: Optional[str] = None
    result_extension: str = "log"


@dataclass
class BpftraceConfig:
    def pg_page_intervals(config: Dict[str, str]) -> "BpftraceConfig":
        script_path = SCRIPT_DIR / "pg_page_intervals.bt"
        parsers = [
            BpftraceParseScript(
                script_path=str(SCRIPT_DIR / "pg_page_intervals_parse.py"),
            )
        ]
        cfg = BpftraceConfig(
            name="pg_page_intervals",
            script_path=str(script_path),
            bpftrace_additional_args="$(id -u postgres)",
            parsers=parsers,
        )
        return cfg._apply_config(config)

    def pg_wal_access(config: Dict[str, str]) -> "BpftraceConfig":
        script_path = SCRIPT_DIR / "pg_wal_access.bt"
        parsers = [
            BpftraceParseScript(
                script_path=str(SCRIPT_DIR / "pg_wal_access_overlaps.py"),
            ),
            BpftraceParseScript(
                script_path=str(SCRIPT_DIR / "pg_wal_access_overview.py"),
                output_path="/tmp/pg_wal_access_overview.png",
                result_extension="png",
            ),
            BpftraceParseScript(
                script_path=str(SCRIPT_DIR / "pg_wal_access_files.py"),
                output_path="/tmp/pg_wal_access_files.png",
                result_extension="png",
            ),
        ]

        cfg = BpftraceConfig(
            name="pg_wal_access",
            script_path=str(script_path),
            bpftrace_additional_args="$(id -u postgres)",
            parsers=parsers,
        )
        return cfg._apply_config(config)

    def cache_misses_by_ino(config: Dict[str, str]) -> "BpftraceConfig":
        script_path = SCRIPT_DIR / "cache_misses_by_ino.bt"
        parsers = [
            BpftraceParseScript(
                script_path=str(SCRIPT_DIR / "cache_misses_by_ino_parse.py"),
            )
        ]
        cfg = BpftraceConfig(
            name="cache_misses_by_ino",
            script_path=str(script_path),
            bpftrace_additional_args="$(id -u postgres)",
            parsers=parsers,
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
    parse_output_path: Optional[str] = None
    parsers: List[BpftraceParseScript] = field(default_factory=list)
    result_extension: str = "log"
    bpftrace_path: str = "/home/jungnoh/bpftrace"
    bpftrace_additional_args: str = ""
    cleanup_timeout: int = 300


class BpftraceClient:
    def __init__(self, target: SshTarget, config: BpftraceConfig):
        self.id = str(uuid.uuid4())
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
        for i in range(len(self.config.parsers)):
            parser = self.config.parsers[i]
            print("Sending bpftrace parse script to the target")
            ssh_copy_file(
                self.target,
                parser.script_path,
                self.remote_parse_script_path(i),
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

    def start(self):
        bpftrace_cmd = (
            f"sudo bash -c 'BPFTRACE_MAX_MAP_KEYS=9999999 nohup {self.config.bpftrace_path} {self.remote_script_path} {self.config.bpftrace_additional_args} "
            + f"> /tmp/probe-{self.id}.out 2>&1 & echo $!'"
        )
        print(f"Running bpftrace command: {bpftrace_cmd}")
        _, stdout, _ = self.ssh.exec_command(bpftrace_cmd)
        pid = int(stdout.read().decode().strip())
        print(f"Bpftrace script started with PID: {pid}")
        self.remote_trace_pid = pid
        time.sleep(2)  # let probes attach

    def stop(self, log: LogConfig):
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

        output_folder = (
            Path(log.log_file_folder()) / "after" / f"bpftrace-{self.config.name}"
        )
        output_folder.mkdir(parents=True, exist_ok=True)
        raw_log_remote_path = f"/tmp/probe-{self.id}.out"

        if len(self.config.parsers) == 0:
            ssh_retrieve_file(
                self.target,
                raw_log_remote_path,
                str(output_folder / "raw.log"),
            )
        for i in range(len(self.config.parsers)):
            parser = self.config.parsers[i]
            print(
                f"Running bpftrace parse script [{i + 1}/{len(self.config.parsers)}]: {parser.script_path}"
            )
            if parser.output_path is None:
                _, stdout, _ = self.ssh.exec_command(
                    f"{self.remote_parse_script_path(i)} {raw_log_remote_path}"
                )
                raw = stdout.read().decode()
                with open(
                    str(output_folder / f"parsed_{i + 1}.{parser.result_extension}"),
                    "w",
                ) as f:
                    f.write(raw)
            else:
                _, stdout, stderr = self.ssh.exec_command(
                    f"{self.remote_parse_script_path(i)} {raw_log_remote_path}"
                )
                print(stdout.read().decode())
                print(stderr.read().decode())
                ssh_retrieve_file(
                    self.target,
                    raw_log_remote_path,
                    str(output_folder / "raw.log"),
                )
                ssh_retrieve_file(
                    self.target,
                    parser.output_path,
                    str(output_folder / f"parsed_{i + 1}.{parser.result_extension}"),
                )

    def cleanup(self):
        self.ssh.close()

    @property
    def remote_script_path(self) -> str:
        return f"/tmp/{self.config.name}.bt"

    def remote_parse_script_path(self, idx: int) -> str:
        return f"/tmp/{self.config.name}_{idx}_parse.py"
