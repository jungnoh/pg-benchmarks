import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from subprocess_tee import run as run_tee


@dataclass
class LogConfig:
    run_id: str
    action: str
    log_root_dir: str = "logs"

    def log_file_folder(self) -> str:
        return f"{self.log_root_dir}/{self.run_id}"

    def log_file_path(self) -> str:
        if "." in self.action:
            return f"{self.log_file_folder()}/{self.action}"
        else:
            return f"{self.log_file_folder()}/{self.action}.log"

    def ensure_log_folder(self) -> None:
        os.makedirs(Path(self.log_file_path()).parent, exist_ok=True)


def shell_command(
    command: str, log: Optional[LogConfig] = None, **kwargs
) -> subprocess.CompletedProcess:
    """
    Executes a single command.
    """
    if log:
        log_file_path = log.log_file_path()
        log.ensure_log_folder()
        result = run_tee(
            command,
            shell=True,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,
        )
        with open(log_file_path, "w") as f:
            if result.stdout is not None:
                f.write(result.stdout)
        return result
    else:
        return run_tee(
            command, shell=True, check=True, text=True, capture_output=True, **kwargs
        )


@dataclass
class SshTarget:
    username: str
    password: Optional[str] = None
    hostname: str = "localhost"
    port: int = 22
    shell: str = "bash"


def ssh_command(
    target: SshTarget, command: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a single command on a remote server.
    """
    return ssh_commands(target, [command], log)


def ssh_commands(
    target: SshTarget, commands: List[str], log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a list of commands on a remote server.
    """
    if target.password is None:
        ssh_cmd = f"ssh {target.username}@{target.hostname} -p {target.port}"
    else:
        ssh_cmd = f"sshpass -p {target.password} ssh {target.username}@{target.hostname} -p {target.port}"

    file = tempfile.NamedTemporaryFile(delete=False)
    file.write("\n".join(commands).encode("utf-8"))
    file.flush()
    file.close()

    result = shell_command(f"cat {file.name} | {ssh_cmd} '{target.shell} -s'", log)
    os.unlink(file.name)
    return result


def ssh_copy_file(
    target: SshTarget, source: str, destination: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Copies a file to a remote server.
    """
    if target.password is None:
        scp_cmd = f"scp -P {target.port} {source} {target.username}@{target.hostname}:{destination}"
    else:
        scp_cmd = f"sshpass -p {target.password} scp -P {target.port} {source} {target.username}@{target.hostname}:{destination}"
    return shell_command(scp_cmd, log)


def ssh_retrieve_file(
    target: SshTarget, source: str, destination: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Retrieves a file from a remote server.
    """
    if target.password is None:
        scp_cmd = f"scp -P {target.port} {target.username}@{target.hostname}:{source} {destination}"
    else:
        scp_cmd = f"sshpass -p {target.password} scp -P {target.port} {target.username}@{target.hostname}:{source} {destination}"
    return shell_command(scp_cmd, log)


@dataclass
class PgTarget:
    username: str
    password: Optional[str] = None
    hostname: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    log_folder: Optional[str] = "/mnt/psql/18/log"


def pg_query(
    target: PgTarget, query: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a single query in a single psql session.
    """
    pg_queries(target, [query], log)


def pg_queries(
    target: PgTarget, queries: List[str], log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a list of queries in a single psql session.
    """
    file = tempfile.NamedTemporaryFile(delete=False)
    file.write("\n".join(queries).encode("utf-8"))
    file.flush()
    file.close()

    result = pg_file(target, file.name, log)
    os.unlink(file.name)
    return result


def pg_file(
    target: PgTarget, filename: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a file in a single psql session.
    """
    if target.password is not None:
        prev_password = os.getenv("PGPASSWORD")
        os.environ["PGPASSWORD"] = target.password

    pg_cmd = f"psql -U {target.username} -h {target.hostname} -p {target.port} -d {target.database} -f {filename}"
    result = shell_command(pg_cmd, log)

    if target.password is not None and prev_password is not None:
        os.environ["PGPASSWORD"] = prev_password

    return result


def pg_query_by_ssh(
    ssh_target: SshTarget, db_name: str, query: str, log: Optional[LogConfig] = None
) -> subprocess.CompletedProcess:
    """
    Executes a single query in a single psql session on a remote server.

    Assumes that the pg user is 'postgres' and the SshTarget user can sudo into postgres user without a password.
    """
    return ssh_command(
        ssh_target, f"sudo -u postgres psql -d {db_name} -c '{query}'", log
    )
