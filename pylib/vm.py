import argparse
import fcntl
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, NoReturn, Optional, Tuple

from . import target_run as run
from .target_run import PgTarget, SshTarget
from .util import read_config_file


SCREEN_BIN = "/usr/bin/screen"


@dataclass
class VMConfig:
    boot_img_path: str
    disk_img_path: str
    shared_path: str
    nvme_pcie_addr: str
    cpu_count: int
    mem_gb: int
    qemu_ssh_port: int = 5555
    qemu_gdb_port: int = 1235
    psql_vm_port: int = 5432
    psql_host_port: int = 35432
    psql_exporter_vm_port: int = 9187
    psql_exporter_host_port: int = 39187
    node_exporter_vm_port: int = 9100
    node_exporter_host_port: int = 39100
    screen_session: str = "pg-benchmark-vm"
    state_dir: str = ".vm-state"
    start_poll_deadline_secs: int = 90

    @classmethod
    def from_file(cls, path: str = "vm.conf") -> "VMConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"VM config file '{path}' not found. "
                f"Copy conf-examples/vm.conf to {path} and edit for your host."
            )
        cfg = read_config_file(path)
        required = [
            "VM_BOOT_IMG_PATH",
            "VM_DISK_IMG_PATH",
            "VM_SHARED_PATH",
            "VM_NVME_PCIE_ADDR",
            "VM_CPU_COUNT",
            "VM_MEM_GB",
        ]
        missing = [k for k in required if not cfg.get(k)]
        if missing:
            raise ValueError(
                f"{path} is missing required keys: {', '.join(missing)}"
            )
        return cls(
            boot_img_path=cfg["VM_BOOT_IMG_PATH"],
            disk_img_path=cfg["VM_DISK_IMG_PATH"],
            shared_path=cfg["VM_SHARED_PATH"],
            nvme_pcie_addr=cfg["VM_NVME_PCIE_ADDR"],
            cpu_count=int(cfg["VM_CPU_COUNT"]),
            mem_gb=int(cfg["VM_MEM_GB"]),
            qemu_ssh_port=int(cfg.get("VM_QEMU_SSH_PORT") or 5555),
            qemu_gdb_port=int(cfg.get("VM_QEMU_GDB_PORT") or 1235),
            psql_vm_port=int(cfg.get("VM_PSQL_VM_PORT") or 5432),
            psql_host_port=int(cfg.get("VM_PSQL_HOST_PORT") or 35432),
            psql_exporter_vm_port=int(cfg.get("VM_PSQL_EXPORTER_VM_PORT") or 9187),
            psql_exporter_host_port=int(cfg.get("VM_PSQL_EXPORTER_HOST_PORT") or 39187),
            node_exporter_vm_port=int(cfg.get("VM_NODE_EXPORTER_VM_PORT") or 9100),
            node_exporter_host_port=int(cfg.get("VM_NODE_EXPORTER_HOST_PORT") or 39100),
            screen_session=cfg.get("VM_SCREEN_SESSION") or "pg-benchmark-vm",
            state_dir=cfg.get("VM_STATE_DIR") or ".vm-state",
            start_poll_deadline_secs=int(
                cfg.get("VM_START_POLL_DEADLINE_SECS") or 90
            ),
        )


@dataclass
class VMStatus:
    pid: int
    cpu: int
    mem_gb: int


class VMController:
    def __init__(self, config: VMConfig):
        self.config = config

    @property
    def pidfile_path(self) -> str:
        return os.path.join(self.config.state_dir, "qemu.pid")

    @property
    def lockfile_path(self) -> str:
        return os.path.join(self.config.state_dir, "vm.lock")

    @property
    def console_log_path(self) -> str:
        return os.path.join(self.config.state_dir, "console.log")

    def status(self) -> Optional[VMStatus]:
        pid = self._read_pidfile()
        if pid is not None and self._is_our_qemu(pid):
            cpu, mem = self._parse_cpu_mem_from_proc(pid)
            return VMStatus(pid=pid, cpu=cpu, mem_gb=mem)
        # Pidfile missing or stale; fall back to scanning by 9p fingerprint
        # so we can still see VMs started outside this controller (e.g. by
        # vmctl.sh manually).
        marker = self._fingerprint_marker()
        result = subprocess.run(
            ["pgrep", "-f", marker],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        first_pid = int(result.stdout.strip().split()[0])
        cpu, mem = self._parse_cpu_mem_from_proc(first_pid)
        return VMStatus(pid=first_pid, cpu=cpu, mem_gb=mem)

    def ensure_running(
        self, ssh: SshTarget, pg: PgTarget, *, force: bool = False
    ) -> None:
        cur = self.status()
        target_cpu = self.config.cpu_count
        target_mem = self.config.mem_gb
        if cur is None:
            print(
                f"VM not running; starting with {target_cpu} CPU, {target_mem}G RAM"
            )
            self.start(target_cpu, target_mem)
        elif force:
            print(
                f"Force restart requested; stopping pid {cur.pid} and "
                f"starting with {target_cpu} CPU, {target_mem}G RAM"
            )
            self.stop()
            self.start(target_cpu, target_mem)
        elif (cur.cpu, cur.mem_gb) != (target_cpu, target_mem):
            print(
                f"VM dimensions ({cur.cpu} CPU, {cur.mem_gb}G) do not match "
                f"vm.conf ({target_cpu} CPU, {target_mem}G); restarting"
            )
            self.stop()
            self.start(target_cpu, target_mem)
        else:
            print(
                f"VM already running with desired dimensions "
                f"({cur.cpu} CPU, {cur.mem_gb}G); verifying readiness"
            )
        self.wait_ready(ssh, pg)

    def start(self, cpu: int, mem_gb: int, *, attach: bool = False) -> None:
        with self._flock():
            self._wipe_dead_session()
            cur = self.status()
            if cur is not None:
                raise RuntimeError(
                    f"VM is already running (pid={cur.pid}, cpu={cur.cpu}, "
                    f"mem={cur.mem_gb}G); refusing to start a second one"
                )
            os.makedirs(self.config.state_dir, exist_ok=True)
            try:
                os.unlink(self.pidfile_path)
            except FileNotFoundError:
                pass
            argv = self._build_screen_argv(cpu, mem_gb)
            print(
                f"Starting VM under screen session "
                f"'{self.config.screen_session}' ({cpu} CPU, {mem_gb}G RAM)"
            )
            subprocess.run(argv, check=True)
            self._wait_for_qemu_alive(cpu, mem_gb)
        if attach:
            self.console()

    def stop(self, *, timeout_secs: int = 60) -> None:
        with self._flock():
            cur = self.status()
            if cur is None:
                self._cleanup_after_stop()
                return
            session = self.config.screen_session
            print(f"Stopping VM (pid={cur.pid}); sending screen quit")
            subprocess.run(
                ["sudo", SCREEN_BIN, "-X", "-S", session, "quit"],
                check=False,
            )
            if self._wait_for_exit(cur.pid, 10):
                self._cleanup_after_stop()
                return
            print(f"Screen quit did not stop QEMU; sending SIGTERM to {cur.pid}")
            subprocess.run(
                ["sudo", "kill", "-TERM", str(cur.pid)], check=False
            )
            if self._wait_for_exit(cur.pid, 15):
                self._cleanup_after_stop()
                return
            print(f"SIGTERM did not stop QEMU; sending SIGKILL to {cur.pid}")
            subprocess.run(
                ["sudo", "kill", "-KILL", str(cur.pid)], check=False
            )
            if not self._wait_for_exit(cur.pid, max(1, timeout_secs - 25)):
                raise RuntimeError(
                    f"Failed to terminate QEMU pid {cur.pid} within "
                    f"{timeout_secs}s"
                )
            self._cleanup_after_stop()

    def console(self) -> NoReturn:
        # Screen session is owned by root (started via `sudo screen -dmS`),
        # so attaching requires sudo too.
        os.execvp(
            "sudo",
            ["sudo", SCREEN_BIN, "-r", self.config.screen_session],
        )

    def wait_ready(self, ssh: SshTarget, pg: PgTarget) -> None:
        print("Waiting for SSH...")
        run.wait_for_ssh_ready(ssh)
        print("Waiting for PostgreSQL...")
        run.wait_for_pg_ready(pg)
        print("VM is ready.")

    # ---- internals ----

    def _fingerprint_marker(self) -> str:
        return (
            f"qemu-system-x86_64.*path={re.escape(self.config.shared_path)}"
            f",mount_tag=hostshare"
        )

    def _read_pidfile(self) -> Optional[int]:
        try:
            with open(self.pidfile_path) as f:
                pid = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return None
        return pid if pid > 0 else None

    def _read_proc_cmdline(self, pid: int) -> Optional[str]:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                return (
                    f.read().replace(b"\0", b" ").decode("utf-8", errors="replace")
                )
        except FileNotFoundError:
            return None

    def _is_our_qemu(self, pid: int) -> bool:
        cmdline = self._read_proc_cmdline(pid)
        if cmdline is None:
            return False
        marker = (
            f"path={self.config.shared_path},mount_tag=hostshare"
        )
        return "qemu-system-x86_64" in cmdline and marker in cmdline

    def _parse_cpu_mem_from_proc(self, pid: int) -> Tuple[int, int]:
        cmdline = self._read_proc_cmdline(pid)
        if cmdline is None:
            raise RuntimeError(f"Cannot read /proc/{pid}/cmdline")
        cpu = self._parse_cpu(cmdline)
        mem = self._parse_mem_gb(cmdline)
        if cpu is None or mem is None:
            raise RuntimeError(
                f"Failed to parse CPU/MEM from QEMU cmdline of pid {pid}: "
                f"{cmdline!r}"
            )
        return cpu, mem

    @staticmethod
    def _parse_cpu(cmdline: str) -> Optional[int]:
        m = re.search(r"-smp\s+(\S+)", cmdline)
        if not m:
            return None
        token = m.group(1)
        cpus_match = re.search(r"cpus=(\d+)", token)
        if cpus_match:
            return int(cpus_match.group(1))
        leading = re.match(r"(\d+)", token)
        if leading:
            return int(leading.group(1))
        return None

    @staticmethod
    def _parse_mem_gb(cmdline: str) -> Optional[int]:
        m = re.search(r"-m\s+(\S+)", cmdline)
        if not m:
            return None
        token = m.group(1)
        if token.endswith(("G", "g")):
            return int(token[:-1])
        if token.endswith(("M", "m")):
            return int(token[:-1]) // 1024
        if token.isdigit():
            return int(token) // 1024
        return None

    def _build_qemu_argv(self, cpu: int, mem_gb: int) -> List[str]:
        c = self.config
        netdev = (
            "user,id=net0,restrict=off,"
            f"hostfwd=tcp::{c.qemu_ssh_port}-:22,"
            f"hostfwd=tcp::{c.psql_host_port}-:{c.psql_vm_port},"
            f"hostfwd=tcp::{c.psql_exporter_host_port}-:{c.psql_exporter_vm_port},"
            f"hostfwd=tcp::{c.node_exporter_host_port}-:{c.node_exporter_vm_port}"
        )
        return [
            "qemu-system-x86_64",
            "-kernel", c.boot_img_path,
            "-cpu", "host",
            "-smp", f"cpus={cpu}",
            "-drive",
            f"file={c.disk_img_path},index=0,media=disk,format=qcow2",
            "-m", f"{mem_gb}G",
            "-append", "root=/dev/sda rw console=ttyS0 selinux=0",
            "--enable-kvm",
            "--nographic",
            "-netdev", netdev,
            "-device", "virtio-net-pci,netdev=net0",
            "-mem-prealloc",
            "-gdb", f"tcp::{c.qemu_gdb_port}",
            "-device", f"vfio-pci,host={c.nvme_pcie_addr}",
            "-virtfs",
            f"local,path={c.shared_path},mount_tag=hostshare,"
            "security_model=mapped-xattr",
            "-pidfile", os.path.abspath(self.pidfile_path),
        ]

    def _build_screen_argv(self, cpu: int, mem_gb: int) -> List[str]:
        os.makedirs(self.config.state_dir, exist_ok=True)
        return [
            "sudo",
            SCREEN_BIN,
            "-dmS", self.config.screen_session,
            "-L", "-Logfile", os.path.abspath(self.console_log_path),
        ] + self._build_qemu_argv(cpu, mem_gb)

    def _wipe_dead_session(self) -> None:
        subprocess.run(
            ["sudo", SCREEN_BIN, "-wipe", self.config.screen_session],
            capture_output=True,
            check=False,
        )

    def _wait_for_qemu_alive(self, expected_cpu: int, expected_mem: int) -> None:
        deadline = time.time() + self.config.start_poll_deadline_secs
        while time.time() < deadline:
            cur = self.status()
            if cur is not None:
                if (cur.cpu, cur.mem_gb) != (expected_cpu, expected_mem):
                    raise RuntimeError(
                        f"QEMU started with unexpected dimensions: got "
                        f"{cur.cpu} CPU/{cur.mem_gb}G, expected "
                        f"{expected_cpu} CPU/{expected_mem}G"
                    )
                return
            time.sleep(1)
        raise TimeoutError(
            f"QEMU did not appear within "
            f"{self.config.start_poll_deadline_secs}s; check "
            f"{self.console_log_path} for boot output"
        )

    def _wait_for_exit(self, pid: int, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._is_our_qemu(pid):
                return True
            time.sleep(1)
        return False

    def _cleanup_after_stop(self) -> None:
        subprocess.run(
            ["sudo", SCREEN_BIN, "-wipe", self.config.screen_session],
            capture_output=True,
            check=False,
        )
        try:
            os.unlink(self.pidfile_path)
        except FileNotFoundError:
            pass

    @contextmanager
    def _flock(self):
        os.makedirs(self.config.state_dir, exist_ok=True)
        f = open(self.lockfile_path, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()


def _load_targets_from_target_conf(path: str = "target.conf") -> Tuple[SshTarget, PgTarget]:
    tcfg = read_config_file(path)
    ssh = SshTarget(
        username=tcfg["SSH_USERNAME"],
        password=tcfg.get("SSH_PASSWORD"),
        hostname=tcfg["SSH_HOST"],
        port=int(tcfg["SSH_PORT"]),
    )
    pg = PgTarget(
        username=tcfg["PG_ADMIN_USERNAME"],
        password=tcfg.get("PG_ADMIN_PASSWORD"),
        hostname=tcfg["PG_ADMIN_HOST"],
        port=int(tcfg["PG_ADMIN_PORT"]),
        database=tcfg["PG_ADMIN_DATABASE"],
    )
    return ssh, pg


def main() -> None:
    parser = argparse.ArgumentParser(prog="vm")
    parser.add_argument(
        "--config", default="vm.conf", help="path to vm.conf (default: vm.conf)"
    )
    parser.add_argument(
        "--target-config",
        default="target.conf",
        help="path to target.conf for ensure-running / wait-ready",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="start the VM")
    p_start.add_argument("--cpu", type=int, help="override VM_CPU_COUNT")
    p_start.add_argument("--mem", type=int, help="override VM_MEM_GB")
    p_start.add_argument(
        "--attach", action="store_true", help="attach to console after start"
    )

    sub.add_parser("stop", help="stop the running VM")
    sub.add_parser("status", help="print pid + cpu + mem_gb")

    p_restart = sub.add_parser("restart", help="stop + start")
    p_restart.add_argument("--cpu", type=int)
    p_restart.add_argument("--mem", type=int)

    sub.add_parser(
        "ensure-running",
        help="reconcile against vm.conf; start/restart as needed",
    )
    sub.add_parser("console", help="attach to the running VM's serial console")
    sub.add_parser(
        "wait-ready", help="block until SSH and PostgreSQL are reachable"
    )

    args = parser.parse_args()
    config = VMConfig.from_file(args.config)
    controller = VMController(config)

    if args.cmd == "start":
        cpu = args.cpu if args.cpu is not None else config.cpu_count
        mem = args.mem if args.mem is not None else config.mem_gb
        controller.start(cpu, mem, attach=args.attach)
    elif args.cmd == "stop":
        controller.stop()
    elif args.cmd == "status":
        st = controller.status()
        if st is None:
            print("not running")
            sys.exit(1)
        print(f"pid={st.pid} cpu={st.cpu} mem_gb={st.mem_gb}")
    elif args.cmd == "restart":
        cpu = args.cpu if args.cpu is not None else config.cpu_count
        mem = args.mem if args.mem is not None else config.mem_gb
        controller.stop()
        controller.start(cpu, mem)
    elif args.cmd == "ensure-running":
        ssh, pg = _load_targets_from_target_conf(args.target_config)
        controller.ensure_running(ssh, pg)
    elif args.cmd == "console":
        controller.console()
    elif args.cmd == "wait-ready":
        ssh, pg = _load_targets_from_target_conf(args.target_config)
        controller.wait_ready(ssh, pg)


if __name__ == "__main__":
    main()
