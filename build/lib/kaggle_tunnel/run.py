import argparse
import getpass
import importlib
import posixpath
import socket
import sys
import time
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 10022
DEFAULT_USER = "notebook"
DEFAULT_REMOTE_DIR = "/kaggle/working"


def ensure_paramiko():
    try:
        return importlib.import_module("paramiko")
    except ImportError:
        print("Installing paramiko...", file=sys.stderr)
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
        return importlib.import_module("paramiko")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload a local Python script to the Kaggle notebook over SSH and run it."
    )
    parser.add_argument("script", help="Path to the local Python script to upload and run.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"SSH host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"SSH port (default: {DEFAULT_PORT})")
    parser.add_argument("--user", default=DEFAULT_USER, help=f"SSH username (default: {DEFAULT_USER})")
    parser.add_argument(
        "--remote-dir",
        default=DEFAULT_REMOTE_DIR,
        help=f"Remote upload directory (default: {DEFAULT_REMOTE_DIR})",
    )
    parser.add_argument(
        "--python",
        default="python",
        help="Python executable to use on the notebook side (default: python)",
    )
    parser.add_argument(
        "--password",
        help="SSH password. If omitted, the script prompts for it.",
    )
    parser.add_argument(
        "--keep-remote-file",
        action="store_true",
        help="Keep the uploaded script after execution.",
    )
    args, script_args = parser.parse_known_args()
    args.script_args = clean_script_args(script_args)
    return args


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def clean_script_args(args):
    if args and args[0] == "--":
        return args[1:]
    return args


def upload_file_over_ssh(client, local_path: Path, remote_path: str) -> None:
    command = f"cat > {shell_quote(remote_path)}"
    stdin, stdout, stderr = client.exec_command(command, timeout=60)
    with local_path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            stdin.channel.sendall(chunk)
    stdin.channel.shutdown_write()
    error_output = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if exit_code != 0:
        raise RuntimeError(f"Remote upload failed with exit code {exit_code}: {error_output.strip()}")


def main():
    args = parse_args()
    script_path = Path(args.script).expanduser().resolve()
    if not script_path.exists():
        print(f"Local script not found: {script_path}", file=sys.stderr)
        return 1
    if script_path.suffix.lower() != ".py":
        print(f"Expected a .py file, got: {script_path.name}", file=sys.stderr)
        return 1

    password = args.password or getpass.getpass("Kaggle SSH password (Shared token): ")
    script_args = args.script_args
    remote_name = f"uploaded_{int(time.time())}_{script_path.name}"
    remote_path = posixpath.join(args.remote_dir, remote_name)

    paramiko = ensure_paramiko()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print(f"Connecting to {args.user}@{args.host}:{args.port} ...", file=sys.stderr)
        client.connect(
            hostname=args.host,
            port=args.port,
            username=args.user,
            password=password,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            banner_timeout=15,
            auth_timeout=15,
        )

        mkdir_command = f"mkdir -p {shell_quote(args.remote_dir)}"
        stdin, stdout, stderr = client.exec_command(mkdir_command, timeout=30)
        stdin.close()
        mkdir_stderr = stderr.read().decode("utf-8", errors="replace")
        mkdir_rc = stdout.channel.recv_exit_status()
        if mkdir_rc != 0:
            print(f"Failed to prepare remote directory: {mkdir_stderr.strip()}", file=sys.stderr)
            return 1

        print(f"Uploading {script_path} -> {remote_path}", file=sys.stderr)
        upload_file_over_ssh(client, script_path, remote_path)

        command_parts = [args.python, remote_path, *script_args]
        remote_command = " ".join(shell_quote(part) for part in command_parts)

        print(f"Running on notebook: {remote_command}", file=sys.stderr)
        stdin, stdout, stderr = client.exec_command(remote_command, timeout=None)
        stdin.close()
        sys.stdout.write(stdout.read().decode("utf-8", errors="replace"))
        sys.stdout.flush()
        sys.stderr.write(stderr.read().decode("utf-8", errors="replace"))
        sys.stderr.flush()
        exit_code = stdout.channel.recv_exit_status()

        if not args.keep_remote_file:
            cleanup_command = f"rm -f {shell_quote(remote_path)}"
            cleanup_stdin, cleanup_stdout, cleanup_stderr = client.exec_command(cleanup_command, timeout=30)
            cleanup_stdin.close()
            cleanup_stderr.read()
            cleanup_stdout.channel.recv_exit_status()

        return exit_code
    except (socket.error, OSError, EOFError) as exc:
        print(f"SSH connection failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to run remote script: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
