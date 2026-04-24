#!/usr/bin/env python3

import argparse
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path


INPUT_MARKER = "__KMUX_INPUT_OK__"
CTRL_C_MARKER = "__KMUX_CTRL_C_START__"


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


def main():
    parser = argparse.ArgumentParser(description="Verify kmux interactive input and Ctrl+C handling.")
    parser.add_argument("--session-file", required=True, help="Path to the active .kmux.session.json file.")
    parser.add_argument("--startup-timeout", type=float, default=8.0)
    parser.add_argument("--command-timeout", type=float, default=4.0)
    args = parser.parse_args()

    session_file = Path(args.session_file).expanduser().resolve()
    if not session_file.exists():
        raise SystemExit(f"Session file not found: {session_file}")

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
        os.close(master_fd)


if __name__ == "__main__":
    main()
