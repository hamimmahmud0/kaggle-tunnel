#!/usr/bin/env python3

import argparse
import os
import shlex
import socket
import subprocess
import threading
from pathlib import Path

import paramiko


HOST_KEY = paramiko.RSAKey.generate(2048)


class FakeServer(paramiko.ServerInterface):
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.shell_event = threading.Event()

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

    def check_channel_shell_request(self, channel):
        self.shell_event.set()
        return True

    def check_channel_pty_request(self, channel, term, width, height, pixelwidth, pixelheight, modes):
        return True


class FakeShell:
    def __init__(self, channel, cwd: Path):
        self.channel = channel
        self.cwd = cwd.resolve()
        self.prompt = self._format_prompt()

    def _format_prompt(self):
        return "\033[1;32mkgtun@fake-remote\033[0m:\033[1;34m%s\033[0m$ " % self.cwd

    def send(self, text: str):
        self.channel.send(text.replace("\n", "\r\n"))

    def clear(self):
        self.channel.send("\033[2J\033[H")

    def run(self):
        self.send("Fake remote ready.\n")
        self.channel.send(self.prompt)
        buffer = ""
        while True:
            data = self.channel.recv(1024)
            if not data:
                break
            buffer += data.decode("utf-8", errors="replace")
            while "\n" in buffer or "\r" in buffer:
                newline_index = min(i for i in [buffer.find("\n"), buffer.find("\r")] if i != -1)
                line = buffer[:newline_index]
                buffer = buffer[newline_index + 1 :]
                self.handle_line(line.strip())
                if self.channel.closed:
                    return

    def handle_line(self, line: str):
        if not line:
            self.channel.send(self.prompt)
            return

        for part in [item.strip() for item in line.split(";") if item.strip()]:
            if part.startswith("cd "):
                target = part[3:].strip()
                target = shlex.split(target)[0] if target else ""
                next_cwd = (self.cwd / target).resolve() if not target.startswith("/") else Path(target)
                if next_cwd.exists() and next_cwd.is_dir():
                    self.cwd = next_cwd
                continue
            if part.startswith("export PS1="):
                continue
            if part.startswith("printf 'Remote cwd: %s\\n' \"$PWD\""):
                self.send(f"Remote cwd: {self.cwd}\n")
                continue
            if part == "clear":
                self.clear()
                continue
            if part in {"exit", "logout"}:
                self.channel.close()
                return

            completed = subprocess.run(
                part,
                shell=True,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            output = completed.stdout or ""
            if output:
                self.send(output)

        self.prompt = self._format_prompt()
        if not self.channel.closed:
            self.channel.send(self.prompt)


def serve_client(client_sock, username: str, password: str, cwd: Path):
    transport = paramiko.Transport(client_sock)
    transport.add_server_key(HOST_KEY)
    server = FakeServer(username, password)
    transport.start_server(server=server)
    channel = transport.accept(20)
    if channel is None:
        transport.close()
        return
    server.shell_event.wait(10)
    if not server.shell_event.is_set():
        channel.close()
        transport.close()
        return
    try:
        FakeShell(channel, cwd).run()
    finally:
        transport.close()


def main():
    parser = argparse.ArgumentParser(description="Fake SSH server for kgtun verification.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", default="notebook")
    parser.add_argument("--password", default="test-token")
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((args.host, args.port))
        server_sock.listen(100)
        print(f"fake-remote listening on {args.host}:{args.port}", flush=True)
        while True:
            client, _ = server_sock.accept()
            thread = threading.Thread(
                target=serve_client,
                args=(client, args.user, args.password, cwd),
                daemon=True,
            )
            thread.start()


if __name__ == "__main__":
    main()
