#!/usr/bin/env python3

import argparse
import asyncio
import json
import os
import pty
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

import asyncssh
from PIL import Image, ImageDraw, ImageFont


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NotebookSSHServer(asyncssh.SSHServer):
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def begin_auth(self, username):
        return True

    def password_auth_supported(self):
        return True

    def validate_password(self, username, password):
        return username == self.username and password == self.password


async def handle_ssh_client(process):
    print("server: handle_ssh_client start", flush=True)
    env = os.environ.copy()
    if getattr(process, "term_type", None):
        env["TERM"] = process.term_type

    term_size = getattr(process, "term_size", None)

    def apply_pty_size(fd, size=None):
        current_size = size or term_size
        if not current_size:
            return
        width, height = int(current_size[0]), int(current_size[1])
        winsize = struct.pack("HHHH", height, width, 0, 0)
        import fcntl

        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)

    def setup_child_pty(slave_fd):
        import fcntl

        os.setsid()
        fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

    if getattr(process, "term_type", None):
        print("server: term_type branch", getattr(process, "term_type", None), flush=True)
        master_fd, slave_fd = pty.openpty()
        apply_pty_size(slave_fd)
        shell = env.get("SHELL") or "/bin/bash"
        shell_argv = [shell, "-i"]
        if os.path.basename(shell) == "bash":
            shell_argv = [shell, "--noprofile", "--norc", "-i"]
        child = subprocess.Popen(
            shell_argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            preexec_fn=lambda: setup_child_pty(slave_fd),
        )
        print(f"server: child pid={child.pid}", flush=True)
        os.close(slave_fd)

        async def pump_ssh_to_pty():
            try:
                while True:
                    try:
                        chunk = await process.stdin.read(65536)
                    except asyncssh.TerminalSizeChanged as exc:
                        apply_pty_size(master_fd, exc.term_size)
                        print(f"server: resized to {exc.term_size}", flush=True)
                        continue
                    if not chunk:
                        print("server: stdin eof", flush=True)
                        break
                    print(f"server: stdin chunk={len(chunk)}", flush=True)
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8", errors="replace")
                    await asyncio.to_thread(os.write, master_fd, chunk)
            except Exception:
                import traceback

                traceback.print_exc()
                pass

        async def pump_pty_to_ssh():
            try:
                while True:
                    chunk = await asyncio.to_thread(os.read, master_fd, 65536)
                    if not chunk:
                        print("server: pty eof", flush=True)
                        break
                    print(f"server: pty chunk={len(chunk)}", flush=True)
                    process.stdout.write(chunk.decode("utf-8", errors="replace"))
                    await process.stdout.drain()
            except Exception:
                import traceback

                traceback.print_exc()
                pass

        ssh_to_pty_task = asyncio.create_task(pump_ssh_to_pty())
        pty_to_ssh_task = asyncio.create_task(pump_pty_to_ssh())
        try:
            await asyncio.wait(
                [ssh_to_pty_task, pty_to_ssh_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            print(
                f"server: wait done stdin_done={ssh_to_pty_task.done()} pty_done={pty_to_ssh_task.done()}",
                flush=True,
            )
        finally:
            for task in (ssh_to_pty_task, pty_to_ssh_task):
                if not task.done():
                    task.cancel()
            if child.poll() is None:
                print("server: terminating child", flush=True)
                child.terminate()
                try:
                    await asyncio.to_thread(child.wait)
                except Exception:
                    child.kill()
            os.close(master_fd)
        returncode = child.returncode if child.returncode is not None else await asyncio.to_thread(child.wait)
        print(f"server: child returncode={returncode}", flush=True)
        process.exit(returncode)
        return

    child = await asyncio.create_subprocess_exec(
        env.get("SHELL") or "/bin/bash",
        "-lc",
        "exec bash --noprofile --norc -i",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    await process.redirect(stdin=child.stdin, stdout=child.stdout, stderr=child.stderr)
    process.exit(await child.wait())


def render_text_image(text: str, image_path: Path):
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    lines = text.splitlines() or [""]
    line_height = 24
    width = 1600
    height = max(400, 40 + line_height * len(lines))
    image = Image.new("RGB", (width, height), "#1f2230")
    draw = ImageDraw.Draw(image)
    y = 20
    for line in lines:
        draw.text((20, y), line, fill="#d8dee9", font=font)
        y += line_height
    image.save(image_path)


async def run_server(port: int, username: str, password: str):
    key = asyncssh.generate_private_key("ssh-rsa")
    await asyncssh.create_server(
        lambda: NotebookSSHServer(username, password),
        "127.0.0.1",
        port,
        server_host_keys=[key],
        process_factory=handle_ssh_client,
    )
    await asyncio.Event().wait()


def capture_pane(session_name: str) -> str:
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", f"{session_name}:0.0"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description="Verify kmux shell against a local asyncssh PTY server.")
    parser.add_argument("--output-dir", default="generated/kmux-notebook-verify")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.mkdtemp(prefix="kmux-notebook-verify-"))
    remote_cwd = temp_root / "remote-workspace"
    remote_cwd.mkdir(parents=True, exist_ok=True)
    (remote_cwd / "hello.txt").write_text("hello from notebook pty verify\n", encoding="utf-8")

    port = find_free_port()
    password = "test-token"
    session_file = temp_root / ".kmux.session.json"
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

    server_process = subprocess.Popen(
        [sys.executable, __file__, "--serve", str(port), "--password", password],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    session_name = f"kmux-notebook-verify-{int(time.time())}"

    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            raise RuntimeError("Verifier server did not start.")

        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session_name,
                "sh",
                "-lc",
                (
                    f"{shutil.which('python') or sys.executable} kmux.py shell "
                    f"--session-file {session_file} ; "
                    "status=$?; "
                    "printf '\\n[wrapper exit %s]\\n' \"$status\"; "
                    "sleep 20"
                ),
            ],
            check=True,
        )

        time.sleep(2)
        subprocess.run(["tmux", "send-keys", "-t", f"{session_name}:0.0", "pwd", "C-m"], check=True)
        time.sleep(0.5)
        subprocess.run(["tmux", "send-keys", "-t", f"{session_name}:0.0", "ls -la", "C-m"], check=True)
        time.sleep(0.5)
        pane_text = capture_pane(session_name)
        text_path = output_dir / "pane.txt"
        image_path = output_dir / "pane.png"
        log_path = output_dir / "server.log"
        text_path.write_text(pane_text, encoding="utf-8")
        render_text_image(pane_text, image_path)
        print(f"Saved pane text to {text_path}")
        print(f"Saved pane image to {image_path}")
        print("--- pane capture ---")
        print(pane_text)
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session_name], check=False)
        server_process.terminate()
        try:
            server_output, _ = server_process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server_process.kill()
            server_output, _ = server_process.communicate()
        (output_dir / "server.log").write_text(server_output or "", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        port = int(sys.argv[2])
        password = sys.argv[4]
        asyncio.run(run_server(port, "notebook", password))
    else:
        main()
