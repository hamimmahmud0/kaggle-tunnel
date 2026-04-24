#!/usr/bin/env python3

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run(*args: str, check: bool = True, capture_output: bool = False, text: bool = True):
    return subprocess.run(args, check=check, capture_output=capture_output, text=text)


def wait_for_port(port: int, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for port {port}.")


def capture_pane_text(session_name: str, pane: str = "0.0") -> str:
    result = run(
        "tmux",
        "capture-pane",
        "-p",
        "-t",
        f"{session_name}:{pane}",
        capture_output=True,
    )
    return result.stdout


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


def main():
    parser = argparse.ArgumentParser(description="Drive kmux shell in tmux and capture a rendered pane image.")
    parser.add_argument("--output-dir", default="generated/kmux-verify")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.mkdtemp(prefix="kmux-verify-"))
    remote_cwd = temp_root / "remote-workspace"
    remote_cwd.mkdir(parents=True, exist_ok=True)
    (remote_cwd / "hello.txt").write_text("hello from fake remote\n", encoding="utf-8")
    fake_log_path = output_dir / "fake-server.log"

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
                "cell_file": str(temp_root / ".kmux.cell"),
                "cwd": str(remote_cwd),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    session_name = f"kmux-verify-{int(time.time())}"

    fake_server = subprocess.Popen(
        [
            sys.executable,
            str(Path("scripts/fake_remote_ssh.py").resolve()),
            "--port",
            str(port),
            "--password",
            password,
            "--cwd",
            str(remote_cwd),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_for_port(port)
        run(
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
                "sleep 30"
            ),
        )

        time.sleep(2)
        run("tmux", "send-keys", "-t", f"{session_name}:0.0", "pwd", "C-m")
        time.sleep(0.5)
        run("tmux", "send-keys", "-t", f"{session_name}:0.0", "ls -la", "C-m")
        time.sleep(0.5)
        run("tmux", "send-keys", "-t", f"{session_name}:0.0", "exit", "C-m")
        time.sleep(0.5)

        pane_text = capture_pane_text(session_name)
        text_path = output_dir / "pane.txt"
        image_path = output_dir / "pane.png"
        text_path.write_text(pane_text, encoding="utf-8")
        render_text_image(pane_text, image_path)
        print(f"Saved pane text to {text_path}")
        print(f"Saved pane image to {image_path}")
        print("--- pane capture ---")
        print(pane_text)
    finally:
        run("tmux", "kill-session", "-t", session_name, check=False)
        fake_server.terminate()
        try:
            fake_output, _ = fake_server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            fake_server.kill()
            fake_output, _ = fake_server.communicate()
        fake_log_path.write_text(fake_output or "", encoding="utf-8")
        print(f"Saved fake server log to {fake_log_path}")


if __name__ == "__main__":
    main()
