#!/usr/bin/env python3

import argparse
import json
import os
import pty
import select
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
from pathlib import Path

import paramiko


INPUT_MARKER = "__KMUX_INPUT_OK__"
CTRL_C_MARKER = "__KMUX_CTRL_C_START__"
HOST_KEY = paramiko.RSAKey.generate(2048)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class PTYServer(paramiko.ServerInterface):
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.shell_event = threading.Event()
        self.term_size = (80, 24)

    def check_auth_password(self, username, password):
        if username == self.username and password == self.password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        self.term_size = (max(1, int(width)), max(1, int(height)))
        return True

    def check_channel_shell_request(self, channel):
        self.shell_event.set()
        return True


def read_until(master_fd: int, timeout_seconds: float) -> bytes:
    chunks = []
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        readers, _, _ = select.select([master_fd], [], [], 0.1)
        if master_fd not in readers:
            continue
        try:
            data = os.read(master_fd, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    return b"".join(chunks)


def bridge_channel_to_pty(channel, master_fd):
    try:
        while True:
            data = channel.recv(1024)
            if not data:
                break
            os.write(master_fd, data)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass


def bridge_pty_to_channel(channel, master_fd):
    try:
        while True:
            try:
                data = os.read(master_fd, 1024)
            except OSError:
                break
            if not data:
                break
            channel.sendall(data)
    finally:
        try:
            channel.close()
        except Exception:
            pass


def serve_client(client_sock, username: str, password: str, cwd: Path):
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(HOST_KEY)
    server = PTYServer(username, password)
    transport.start_server(server=server)
    channel = transport.accept(20)
    if channel is None:
        transport.close()
        return
    if not server.shell_event.wait(10):
        channel.close()
        transport.close()
        return

    master_fd, slave_fd = pty.openpty()
    winsize = struct.pack("HHHH", server.term_size[1], server.term_size[0], 0, 0)
    __import__("fcntl").ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
    child = subprocess.Popen(
        [os.environ.get("SHELL") or "/bin/bash", "--noprofile", "--norc", "-i"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=str(cwd),
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    to_pty = threading.Thread(target=bridge_channel_to_pty, args=(channel, master_fd), daemon=True)
    from_pty = threading.Thread(target=bridge_pty_to_channel, args=(channel, master_fd), daemon=True)
    to_pty.start()
    from_pty.start()
    try:
        while child.poll() is None and transport.is_active():
            time.sleep(0.1)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
        transport.close()


def run_server(host: str, port: int, username: str, password: str, cwd: Path, stop_event: threading.Event):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((host, port))
        server_sock.listen(100)
        server_sock.settimeout(0.5)
        while not stop_event.is_set():
            try:
                client, _ = server_sock.accept()
            except socket.timeout:
                continue
            thread = threading.Thread(
                target=serve_client,
                args=(client, username, password, cwd),
                daemon=True,
            )
            thread.start()


def main():
    parser = argparse.ArgumentParser(description="Verify kmux interactive input and Ctrl+C using a local PTY SSH server.")
    parser.add_argument("--startup-timeout", type=float, default=6.0)
    parser.add_argument("--command-timeout", type=float, default=3.0)
    args = parser.parse_args()

    temp_root = Path(tempfile.mkdtemp(prefix="kmux-local-pty-verify-"))
    remote_cwd = temp_root / "remote-workspace"
    remote_cwd.mkdir(parents=True, exist_ok=True)
    session_file = temp_root / ".kmux.session.json"
    port = find_free_port()
    password = "test-token"

    session_file.write_text(
        json.dumps(
            {
                "status": "connected",
                "remote_connected": True,
                "proxy_port": port,
                "shared_token": password,
                "ssh_user": "notebook",
                "cell_file": str(temp_root / "kmux.cell"),
                "cwd": str(remote_cwd),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    stop_event = threading.Event()
    server_thread = threading.Thread(
        target=run_server,
        args=("127.0.0.1", port, "notebook", password, remote_cwd, stop_event),
        daemon=True,
    )
    server_thread.start()

    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        [sys.executable, "kmux.py", "shell", "--session-file", str(session_file)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)

    try:
        output = read_until(master_fd, args.startup_timeout)

        os.write(master_fd, f'printf "{INPUT_MARKER}\\n"\r'.encode("utf-8"))
        output += read_until(master_fd, args.command_timeout)

        long_command = f'python -c \'import time; print("{CTRL_C_MARKER}", flush=True); time.sleep(30)\''
        os.write(master_fd, (long_command + "\r").encode("utf-8"))
        output += read_until(master_fd, args.command_timeout)

        os.write(master_fd, b"\x03")
        output += read_until(master_fd, args.command_timeout)

        text = output.decode("utf-8", errors="replace")
        process_exited = process.poll() is not None
        input_ok = INPUT_MARKER in text
        ctrl_c_started = CTRL_C_MARKER in text
        after_ctrl_c = text.rsplit("^C", 1)[-1] if "^C" in text else ""
        prompt_returned = "$ " in after_ctrl_c or "# " in after_ctrl_c

        print(text)
        print(f"process_exited={process_exited}")
        print(f"input_ok={input_ok}")
        print(f"ctrl_c_started={ctrl_c_started}")
        print(f"prompt_returned={prompt_returned}")

        if process_exited:
            raise SystemExit("kmux shell exited unexpectedly during interactive test.")
        if not input_ok:
            raise SystemExit("kmux did not forward regular input to the remote shell.")
        if not ctrl_c_started:
            raise SystemExit("kmux did not start the long-running Ctrl+C test command.")
        if not prompt_returned:
            raise SystemExit("kmux did not return to the remote prompt after Ctrl+C.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        stop_event.set()
        server_thread.join(timeout=2)
        os.close(master_fd)


if __name__ == "__main__":
    main()
