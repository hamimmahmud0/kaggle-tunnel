import argparse
import json
import os
import platform
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path
from select import select

import kaggle_tunnel.app as app_module

from .app import (
    DEFAULT_PROXY_HOST,
    DEFAULT_PROXY_TARGET_PORT,
    TunnelRuntime,
    find_cloudflared,
)
from .run import DEFAULT_USER, ensure_paramiko


MIN_PORT = 1201
DEFAULT_CONTROL_PORT = 8765
DEFAULT_PROXY_PORT = 10022
SESSION_READY_TIMEOUT_SECONDS = 90
CLI_NAME = "kmux"
SESSION_FILE_NAME = ".kmux.session.json"
CELL_FILE_NAME = ".kmux.cell"
LOG_FILE_NAME = "kmux.log"


def get_kgtun_config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / CLI_NAME


KGTUN_CONFIG_DIR = get_kgtun_config_dir()
KGTUN_SESSIONS_DIR = KGTUN_CONFIG_DIR / "sessions"
KGTUN_CLOUDFLARED_HOME_DIR = KGTUN_CONFIG_DIR / "cloudflared-home"
KGTUN_STATE_FILE = KGTUN_CONFIG_DIR / "state.json"


def now_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def ensure_kgtun_runtime_files():
    for directory in (KGTUN_CONFIG_DIR, KGTUN_SESSIONS_DIR, KGTUN_CLOUDFLARED_HOME_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    state = {
        "created_at": now_timestamp(),
        "python_executable": sys.executable,
        "app_module_file": str(Path(app_module.__file__).resolve()),
        "kmux_module_file": str(Path(__file__).resolve()),
        "platform": platform.platform(),
        "tmux_path": shutil.which("tmux") or "",
        "cloudflared_home": str(KGTUN_CLOUDFLARED_HOME_DIR),
    }
    KGTUN_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def ensure_tmux():
    if shutil.which("tmux") is None:
        raise RuntimeError(f"tmux is required for {CLI_NAME} but was not found on PATH.")


def find_free_port(start_port: int) -> int:
    port = max(start_port, MIN_PORT)
    while port <= 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                continue
        return port
    raise RuntimeError(f"Unable to find a free TCP port starting at {start_port}.")


class SessionStore:
    def __init__(self, session_file: Path):
        self.session_file = session_file
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if not self.session_file.exists():
            return {}
        return json.loads(self.session_file.read_text(encoding="utf-8"))

    def write(self):
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self.session_file.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")

    def update(self, **updates):
        with self.lock:
            self.data.update(updates)
            self.data["updated_at"] = now_timestamp()
            self.write()

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)


def write_initial_session_file(session_file: Path, cwd: Path, session_name: str):
    session_store = SessionStore(session_file)
    session_store.update(
        session_name=session_name,
        cwd=str(cwd),
        cell_file=str(cwd / CELL_FILE_NAME),
        log_file=str(cwd / LOG_FILE_NAME),
        status="starting",
        created_at=now_timestamp(),
        remote_connected=False,
    )


def shell_join(parts: list[str]) -> str:
    return shlex.join(parts)


def run_tmux(*args: str):
    subprocess.run(["tmux", *args], check=True)


def try_run_tmux(*args: str) -> bool:
    try:
        run_tmux(*args)
        return True
    except subprocess.CalledProcessError:
        return False


def build_module_command(*args: str) -> str:
    return shell_join([sys.executable, "-m", "kaggle_tunnel.kgtun", *args])


def build_module_argv(*args: str) -> list[str]:
    return [sys.executable, "-m", "kaggle_tunnel.kgtun", *args]


def create_tmux_session(session_name: str, cwd: Path, session_file: Path):
    shell_command = build_module_command("shell", "--session-file", str(session_file))
    cleanup_command = build_module_command("cleanup", "--session-file", str(session_file))

    run_tmux("new-session", "-d", "-s", session_name, "-c", str(cwd), shell_command)
    run_tmux("rename-window", "-t", f"{session_name}:0", "notebook")
    try_run_tmux("set-option", "-t", session_name, "default-command", shell_command)
    run_tmux(
        "set-hook",
        "-t",
        session_name,
        "session-closed",
        f"run-shell -b {shlex.quote(cleanup_command)}",
    )


def attach_tmux_session(session_name: str):
    if os.environ.get("TMUX"):
        run_tmux("switch-client", "-t", session_name)
        return
    os.execvp("tmux", ["tmux", "attach-session", "-t", session_name])


def generate_session_name() -> str:
    return f"{CLI_NAME}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def wait_for_session_artifacts(session_file: Path, timeout_seconds: int = SESSION_READY_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if session_file.exists():
            data = json.loads(session_file.read_text(encoding="utf-8"))
            cell_file = Path(data.get("cell_file", ""))
            if data.get("public_url") and cell_file.exists():
                return data
            if data.get("status") == "failed":
                raise RuntimeError(data.get("error", f"{CLI_NAME} session failed to start."))
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {CLI_NAME} to produce the notebook cell.")


def launch_kgtun(cwd: Path):
    ensure_kgtun_runtime_files()
    ensure_tmux()
    KGTUN_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session_name = generate_session_name()
    session_dir = KGTUN_SESSIONS_DIR / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / SESSION_FILE_NAME
    write_initial_session_file(session_file, cwd, session_name)
    create_tmux_session(session_name, cwd, session_file)
    controller_process = start_controller_process(session_file, cwd)
    try:
        wait_for_session_artifacts(session_file)
        attach_tmux_session(session_name)
    except Exception:
        stop_controller_process(session_file, controller_process.pid)
        try_run_tmux("kill-session", "-t", session_name)
        raise


def log_line(log_file: Path, message: str):
    timestamped = f"[{time.strftime('%H:%M:%S')}] {message}"
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(timestamped + "\n")


def write_cell_file(cell_path: Path, cell_code: str):
    cell_path.write_text(cell_code, encoding="utf-8")


def start_controller_process(session_file: Path, cwd: Path) -> subprocess.Popen:
    session_store = SessionStore(session_file)
    log_file = Path(session_store.get("log_file", str(cwd / LOG_FILE_NAME))).resolve()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as handle:
        process = subprocess.Popen(
            build_module_argv("serve", "--session-file", str(session_file)),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    session_store.update(controller_pid=process.pid)
    return process


def stop_controller_process(session_file: Path, controller_pid: int | None = None):
    session_store = SessionStore(session_file)
    pid = controller_pid or session_store.get("controller_pid")
    if not pid:
        return
    try:
        os.kill(int(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    session_store.update(controller_pid=None)


def serve_session(session_file: Path):
    ensure_kgtun_runtime_files()
    os.environ["KAGGLE_TUNNEL_CLOUDFLARED_HOME"] = str(KGTUN_CLOUDFLARED_HOME_DIR)
    app_module.CLOUDFLARED_HOME_DIR = KGTUN_CLOUDFLARED_HOME_DIR

    session_store = SessionStore(session_file)
    cwd = Path(session_store.get("cwd", os.getcwd())).resolve()
    cell_file = Path(session_store.get("cell_file", str(cwd / CELL_FILE_NAME))).resolve()
    log_file = Path(session_store.get("log_file", str(cwd / LOG_FILE_NAME))).resolve()
    log_file.parent.mkdir(parents=True, exist_ok=True)

    runtime = TunnelRuntime(
        log_callback=lambda message: log_line(log_file, message),
        state_callback=lambda **kwargs: on_runtime_state(session_store, **kwargs),
    )
    stop_event = threading.Event()

    def request_stop(*_args):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    cloudflared_path = find_cloudflared()
    if cloudflared_path is None:
        session_store.update(status="failed", error="cloudflared executable was not found.")
        raise RuntimeError("cloudflared executable was not found.")

    control_port = find_free_port(DEFAULT_CONTROL_PORT)
    proxy_port = find_free_port(max(control_port + 1, DEFAULT_PROXY_PORT))
    token = secrets.token_urlsafe(24)

    session_store.update(
        status="starting",
        control_port=control_port,
        proxy_port=proxy_port,
        proxy_host="127.0.0.1",
        ssh_user=DEFAULT_USER,
        shared_token=token,
        log_file=str(log_file),
        config_dir=str(KGTUN_CONFIG_DIR),
        cloudflared_home=str(KGTUN_CLOUDFLARED_HOME_DIR),
    )

    try:
        runtime.run_coro(runtime.start_server(control_port, token)).result()
        runtime.start_cloudflared(cloudflared_path)

        deadline = time.monotonic() + SESSION_READY_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if runtime.public_url:
                break
            if stop_event.wait(0.25):
                return
        if not runtime.public_url:
            raise RuntimeError("Timed out waiting for the public tunnel URL to become ready.")

        runtime.run_coro(
            runtime.start_proxy(proxy_port, DEFAULT_PROXY_HOST, DEFAULT_PROXY_TARGET_PORT)
        ).result()

        cell_code = runtime.build_notebook_cell_code()
        write_cell_file(cell_file, cell_code)
        session_store.update(
            status="awaiting_notebook",
            public_url=runtime.public_url,
            cell_file=str(cell_file),
        )
        log_line(log_file, f"Notebook cell written to {cell_file}")
        log_line(log_file, f"Run the code in {CELL_FILE_NAME} on Kaggle, then use the shell pane.")

        while not stop_event.wait(0.5):
            pass
    except Exception as exc:
        session_store.update(status="failed", error=str(exc))
        raise
    finally:
        session_store.update(controller_pid=None)
        runtime.stop_cloudflared()
        try:
            runtime.run_coro(runtime.stop_server()).result(timeout=5)
        except Exception:
            pass


def on_runtime_state(session_store: SessionStore, public_url=None, remote_connected=None, remote_info=None):
    updates = {}
    if public_url is not None:
        updates["public_url"] = public_url or ""
    if remote_connected is not None:
        updates["remote_connected"] = bool(remote_connected)
        updates["status"] = "connected" if remote_connected else "awaiting_notebook"
    if remote_info is not None:
        updates["remote_info"] = remote_info
    if updates:
        session_store.update(**updates)


def wait_for_session_data(session_file: Path):
    while True:
        if session_file.exists():
            data = json.loads(session_file.read_text(encoding="utf-8"))
            if data.get("status") == "failed":
                raise RuntimeError(data.get("error", f"{CLI_NAME} session failed."))
            if data.get("proxy_port") and data.get("shared_token"):
                return data
        time.sleep(0.5)


def wait_for_remote_connection(session_file: Path, proxy_port: int, cell_file: str):
    announced_wait = False
    while True:
        data = json.loads(session_file.read_text(encoding="utf-8"))
        if data.get("status") == "failed":
            raise RuntimeError(data.get("error", f"{CLI_NAME} session failed."))
        if data.get("remote_connected"):
            print("Notebook connected. Starting SSH session...", flush=True)
            return data
        if not announced_wait:
            print(
                f"Waiting for notebook to connect on 127.0.0.1:{proxy_port}. "
                f"Run the code in {cell_file} first.",
                flush=True,
            )
            announced_wait = True
        time.sleep(1)


def maybe_resize_channel(channel):
    columns, rows = shutil.get_terminal_size((80, 24))
    channel.resize_pty(width=columns, height=rows)


def wait_for_initial_shell_prompt(channel, timeout_seconds: float = 2.0):
    deadline = time.monotonic() + timeout_seconds
    saw_data = False
    while time.monotonic() < deadline:
        if channel.recv_ready():
            saw_data = True
            channel.recv(65536)
        elif saw_data:
            return
        time.sleep(0.05)


def interactive_shell(client, remote_cwd: str):
    channel = client.invoke_shell(term=os.environ.get("TERM", "xterm-256color"))
    maybe_resize_channel(channel)
    wait_for_initial_shell_prompt(channel)

    bootstrap_commands = [
        f"cd {shlex.quote(remote_cwd)} 2>/dev/null || cd /kaggle/working 2>/dev/null || true",
        rf"export PS1=$'\e[1;32m{CLI_NAME}@\h\e[0m:\e[1;34m\w\e[0m\$ '",
        r"printf 'Remote cwd: %s\n' \"$PWD\"",
        "clear",
    ]
    for command in bootstrap_commands:
        channel.send(command + "\r")

    old_tty = termios.tcgetattr(sys.stdin.fileno())

    def handle_resize(_signum, _frame):
        try:
            maybe_resize_channel(channel)
        except Exception:
            pass

    previous_winch = signal.getsignal(signal.SIGWINCH)
    signal.signal(signal.SIGWINCH, handle_resize)
    tty.setraw(sys.stdin.fileno())
    tty.setcbreak(sys.stdin.fileno())

    try:
        while True:
            readers, _, _ = select([channel, sys.stdin], [], [])
            if channel in readers:
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                if channel.exit_status_ready() and not channel.recv_ready():
                    break
            if sys.stdin in readers:
                data = os.read(sys.stdin.fileno(), 1024)
                if not data:
                    break
                channel.send(data)
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty)
        signal.signal(signal.SIGWINCH, previous_winch)
        channel.close()


def connect_shell(session_file: Path):
    ensure_kgtun_runtime_files()
    session_data = wait_for_session_data(session_file)
    proxy_port = int(session_data["proxy_port"])
    shared_token = session_data["shared_token"]
    ssh_user = session_data.get("ssh_user", DEFAULT_USER)
    cell_file = session_data.get("cell_file", str(Path.cwd() / CELL_FILE_NAME))
    remote_cwd = session_data.get("cwd", "/kaggle/working")

    paramiko = ensure_paramiko()

    wait_for_remote_connection(session_file, proxy_port, cell_file)

    while True:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname="127.0.0.1",
                port=proxy_port,
                username=ssh_user,
                password=shared_token,
                look_for_keys=False,
                allow_agent=False,
                timeout=10,
                banner_timeout=15,
                auth_timeout=15,
            )
            print(f"Connected to notebook on 127.0.0.1:{proxy_port}.", flush=True)
            interactive_shell(client, remote_cwd)
            return
        except (socket.error, OSError, EOFError, paramiko.SSHException) as exc:
            print(f"SSH not ready yet: {exc}", flush=True)
            time.sleep(2)
        finally:
            client.close()


def parse_args():
    if len(sys.argv) > 1 and sys.argv[1] in {"serve", "shell", "cleanup"}:
        parser = argparse.ArgumentParser(prog=f"{CLI_NAME} {sys.argv[1]}")
        parser.add_argument("--session-file", required=True)
        args = parser.parse_args(sys.argv[2:])
        args.subcommand = sys.argv[1]
        return args

    parser = argparse.ArgumentParser(
        prog=CLI_NAME,
        description="Start a Kaggle notebook tunnel and open a tmux session around it.",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help=f"Working directory where {CELL_FILE_NAME} and {LOG_FILE_NAME} will be written (default: current directory).",
    )
    args = parser.parse_args()
    args.subcommand = None
    return args


def main():
    args = parse_args()
    if args.subcommand == "serve":
        serve_session(Path(args.session_file).resolve())
        return
    if args.subcommand == "shell":
        connect_shell(Path(args.session_file).resolve())
        return
    if args.subcommand == "cleanup":
        stop_controller_process(Path(args.session_file).resolve())
        return
    launch_kgtun(Path(args.cwd).resolve())


if __name__ == "__main__":
    main()
