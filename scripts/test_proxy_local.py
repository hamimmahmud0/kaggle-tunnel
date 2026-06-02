#!/usr/bin/env python3
"""
End-to-end test for the reversed-direction SSH proxy.

Simulates both sides locally:
  ┌─ "VM" side (notebook) ──────────────────────┐
  │  SSH server (asyncssh) :2222                 │
  │  WS proxy (aiohttp)    :8765 → bridges to SSH│
  └──────────────────────────────────────────────┘
                    ↑ WebSocket (ws://127.0.0.1:8765/ws)
                    │ with x-kaggle-tunnel-token header
  ┌─ PC side (proxy) ────────────────────────────┐
  │  proxy.py connects to WS, listens on :10022   │
  │  ssh connects to 127.0.0.1:10022              │
  └──────────────────────────────────────────────┘

Usage:
    python scripts/test_proxy_local.py [--token TOKEN] [--password PASSWORD]
"""

import argparse
import asyncio
import base64
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger("test-proxy")


# ── Helpers ────────────────────────────────────────────────────────────

def _first_10_alpha(s: str) -> str:
    return "".join(c for c in s if c.isalpha())[:10]


def find_free_port(start: int = 10022, end: int = 20000) -> int:
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port in range {start}-{end}")


# ── "VM" side: SSH server + WS proxy (same as notebook_cell.py) ───────

class VMEnvironment:
    """Simulates the notebook VM: SSH server + WebSocket proxy."""

    def __init__(self, token: str, ssh_password: str, ssh_port: int = 2222, ws_port: int = 8765):
        self.token = token
        self.ssh_password = ssh_password
        self.ssh_port = ssh_port
        self.ws_port = ws_port
        self.ssh_server = None
        self.ws_runner = None
        self.ws_site = None
        self._conns: dict[str, tuple] = {}

    async def start(self):
        """Start SSH server + WS proxy."""
        # ── SSH server ──
        import asyncssh

        host_key_path = Path(tempfile.mkdtemp()) / "ssh_host_key"
        if not host_key_path.exists():
            asyncssh.generate_private_key("ssh-rsa").write_private_key(str(host_key_path))

        class TestSSHServer(asyncssh.SSHServer):
            def begin_auth(self, _username):
                return True
            def password_auth_supported(self):
                return True
            def validate_password(self, username, password):
                return username == "notebook" and password == self.password

        TestSSHServer.password = self.ssh_password  # type: ignore

        async def handle_client(process):
            """Simple shell handler."""
            env = os.environ.copy()
            if getattr(process, "term_type", None):
                env["TERM"] = process.term_type

            shell = env.get("SHELL") or "/bin/bash"
            shell_argv = [shell, "-i"]
            if os.path.basename(shell) == "bash":
                shell_argv = [shell, "--noprofile", "--norc", "-i"]

            if process.command:
                child = subprocess.Popen(
                    process.command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                await process.redirect(
                    stdin=child.stdin,
                    stdout=child.stdout,
                    stderr=child.stderr,
                )
                process.exit(await asyncio.to_thread(child.wait))
                return
            else:
                # PTY-based interactive
                import pty, struct, termios, fcntl
                master_fd, slave_fd = pty.openpty()
                try:
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                except Exception:
                    pass
                child = subprocess.Popen(
                    shell_argv,
                    stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                    env=env, close_fds=True,
                    preexec_fn=os.setsid,
                )
                os.close(slave_fd)

                async def pump_ssh_to_pty():
                    try:
                        while True:
                            try:
                                chunk = await process.stdin.read(1024)
                            except asyncssh.TerminalSizeChanged:
                                continue
                            if not chunk:
                                break
                            if isinstance(chunk, str):
                                chunk = chunk.encode("utf-8", errors="replace")
                            await asyncio.to_thread(os.write, master_fd, chunk)
                    except Exception:
                        pass

                async def pump_pty_to_ssh():
                    try:
                        while True:
                            chunk = await asyncio.to_thread(os.read, master_fd, 65536)
                            if not chunk:
                                break
                            process.stdout.write(chunk)
                            await process.stdout.drain()
                    except Exception:
                        pass

                t1 = asyncio.create_task(pump_ssh_to_pty())
                t2 = asyncio.create_task(pump_pty_to_ssh())
                try:
                    await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)
                finally:
                    for t in (t1, t2):
                        if not t.done():
                            t.cancel()
                    if child.poll() is None:
                        child.terminate()
                    os.close(master_fd)
                process.exit(child.returncode or 0)

        self.ssh_server = await asyncssh.create_server(
            TestSSHServer, "127.0.0.1", self.ssh_port,
            server_host_keys=[str(host_key_path)],
            process_factory=handle_client,
            encoding=None,
        )
        logger.info("VM SSH server on 127.0.0.1:%d  password=%s", self.ssh_port, self.ssh_password)

        # ── WS proxy ──
        import aiohttp
        import aiohttp.web

        async def ws_handle(request):
            ws = aiohttp.web.WebSocketResponse(max_msg_size=0)
            await ws.prepare(request)

            # Auth gate
            token = request.headers.get("x-kaggle-tunnel-token", "") or request.query.get("token", "")
            if token != self.token:
                await ws.send_json({"type": "error", "message": "invalid token"})
                await ws.close()
                return ws

            await ws.send_json({
                "type": "hello",
                "hostname": "test-vm",
                "instance_name": "test-instance",
                "ssh_user": "notebook",
                "ssh_port": self.ssh_port,
            })

            try:
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        payload = json.loads(msg.data)
                        t = payload.get("type")
                        if t == "tcp_open":
                            asyncio.create_task(self._proxy_tcp(ws, payload))
                        elif t == "tcp_data":
                            await self._forward_tcp(payload)
                        elif t == "tcp_close":
                            self._close_tcp(payload["connection_id"])
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                        break
            except Exception:
                pass
            finally:
                for cid in list(self._conns.keys()):
                    self._close_tcp(cid)
            return ws

        app = aiohttp.web.Application()
        app.router.add_get("/ws", ws_handle)
        app.router.add_get("/healthz", lambda r: aiohttp.web.Response(text="ok"))
        self.ws_runner = aiohttp.web.AppRunner(app)
        await self.ws_runner.setup()
        self.ws_site = aiohttp.web.TCPSite(self.ws_runner, "127.0.0.1", self.ws_port)
        await self.ws_site.start()
        logger.info("VM WS proxy on ws://127.0.0.1:%d/ws  token=%s", self.ws_port, self.token)

    async def _proxy_tcp(self, ws, payload):
        cid = payload["connection_id"]
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self.ssh_port)
        except Exception as exc:
            await ws.send_json({"type": "tcp_closed", "connection_id": cid, "error": str(exc)})
            return

        async def pump():
            try:
                while True:
                    chunk = await reader.read(65536)
                    if not chunk:
                        break
                    await ws.send_json({
                        "type": "tcp_data",
                        "connection_id": cid,
                        "data": base64.b64encode(chunk).decode("ascii"),
                    })
            except Exception:
                pass
            finally:
                await ws.send_json({"type": "tcp_closed", "connection_id": cid})

        task = asyncio.create_task(pump())
        self._conns[cid] = (writer, task)
        await ws.send_json({"type": "tcp_opened", "connection_id": cid})

    async def _forward_tcp(self, payload):
        entry = self._conns.get(payload["connection_id"])
        if not entry:
            return
        writer, _ = entry
        writer.write(base64.b64decode(payload["data"]))
        await writer.drain()

    def _close_tcp(self, cid):
        entry = self._conns.pop(cid, None)
        if not entry:
            return
        writer, task = entry
        try:
            writer.close()
        except Exception:
            pass
        if not task.done():
            task.cancel()

    async def stop(self):
        """Shutdown VM environment."""
        if self.ws_runner:
            await self.ws_runner.cleanup()
        if self.ssh_server:
            self.ssh_server.close()
            await self.ssh_server.wait_closed()
        logger.info("VM environment stopped")


# ── PC-side proxy (inline, same logic as proxy.py) ───────────────────

async def run_pc_proxy(
    tunnel_url: str,
    group_token: str,
    local_port: int,
    ssh_port: int = 2222,
) -> asyncio.AbstractServer:
    """Start PC-side proxy. Returns the server object."""
    import aiohttp

    async def handle_client(reader, writer):
        conn_id = f"ssh-{id(reader)}"
        headers = {"x-kaggle-tunnel-token": group_token}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.ws_connect(
                    tunnel_url, max_msg_size=0, heartbeat=20.0
                ) as ws:
                    await ws.send_json({
                        "type": "tcp_open",
                        "connection_id": conn_id,
                        "host": "127.0.0.1",
                        "port": ssh_port,
                    })

                    # Wait for VM to confirm
                    confirmed = False
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            ptype = payload.get("type")
                            if ptype == "tcp_opened" and payload.get("connection_id") == conn_id:
                                confirmed = True
                                break
                            elif ptype == "tcp_closed" and payload.get("connection_id") == conn_id:
                                err = payload.get("error", "unknown error")
                                raise ConnectionError(f"VM TCP proxy failed: {err}")
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                            break
                    if not confirmed:
                        raise TimeoutError("VM did not confirm TCP connection")

                    async def pump_to_ws():
                        try:
                            while True:
                                chunk = await reader.read(65536)
                                if not chunk:
                                    break
                                await ws.send_json({
                                    "type": "tcp_data",
                                    "connection_id": conn_id,
                                    "data": base64.b64encode(chunk).decode("ascii"),
                                })
                        except Exception:
                            pass
                        finally:
                            try:
                                await ws.send_json({
                                    "type": "tcp_close",
                                    "connection_id": conn_id,
                                })
                            except Exception:
                                pass

                    pump_task = asyncio.create_task(pump_to_ws())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(msg.data)
                                ptype = payload.get("type")
                                if ptype == "tcp_data" and payload.get("connection_id") == conn_id:
                                    writer.write(base64.b64decode(payload["data"]))
                                    await writer.drain()
                                elif ptype == "tcp_closed" and payload.get("connection_id") == conn_id:
                                    break
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                                break
                    finally:
                        pump_task.cancel()
                        try:
                            await pump_task
                        except asyncio.CancelledError:
                            pass
        except Exception as exc:
            logger.error("Proxy error: %s", exc)
            err_msg = f"Proxy error: {exc}\n".encode()
            try:
                writer.write(err_msg)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    server = await asyncio.start_server(handle_client, "127.0.0.1", local_port)
    logger.info("PC proxy on 127.0.0.1:%d -> ws://127.0.0.1:%s (SSH :%d)", local_port, tunnel_url.split(":")[-1].rstrip("/ws"), ssh_port)
    return server


# ── Main test ──────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="End-to-end SSH proxy test")
    parser.add_argument("--token", default="test-group-token-abc123", help="Group token for auth")
    parser.add_argument("--password", default=None, help="SSH password (default: first 10 alpha of token)")
    parser.add_argument("--vm-ssh-port", type=int, default=2222, help="VM SSH server port")
    parser.add_argument("--vm-ws-port", type=int, default=8765, help="VM WS proxy port")
    parser.add_argument("--proxy-port", type=int, default=None, help="PC proxy local port")
    args = parser.parse_args()

    token = args.token
    password = args.password if args.password else _first_10_alpha(token)
    proxy_port = args.proxy_port or find_free_port(10022)
    ws_url = f"ws://127.0.0.1:{args.vm_ws_port}/ws"

    logger.info("=" * 60)
    logger.info("Starting end-to-end SSH proxy test")
    logger.info("=" * 60)
    logger.info("Token:            %s", token)
    logger.info("SSH password:     %s", password)
    logger.info("VM SSH port:      %d", args.vm_ssh_port)
    logger.info("VM WS port:       %d", args.vm_ws_port)
    logger.info("PC proxy port:    %d", proxy_port)
    logger.info("WS URL:           %s", ws_url)
    logger.info("")

    # ── Start VM environment ──
    vm = VMEnvironment(token=token, ssh_password=password, ssh_port=args.vm_ssh_port, ws_port=args.vm_ws_port)
    await vm.start()
    logger.info("")

    # ── Start PC proxy ──
    proxy_server = await run_pc_proxy(ws_url, token, proxy_port, args.vm_ssh_port)
    logger.info("")

    # Give things time to settle
    await asyncio.sleep(0.5)

    # ── Test SSH connection ──
    ssh_cmd = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=accept-new",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "LogLevel=ERROR",
        "-p", str(proxy_port),
        "notebook@127.0.0.1",
        "echo 'SSH_PROXY_TEST_OK' && hostname && whoami",
    ]
    logger.info("Running: %s", " ".join(ssh_cmd))
    logger.info("")

    proc = await asyncio.create_subprocess_exec(
        *ssh_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        logger.error("SSH test TIMED OUT after 15s")
        logger.info("")
        logger.info("Cleaning up...")
        proxy_server.close()
        await proxy_server.wait_closed()
        await vm.stop()
        sys.exit(1)

    # ── Check result ──
    logger.info("")
    logger.info("─" * 60)
    if proc.returncode == 0:
        output = stdout.decode("utf-8", errors="replace").strip()
        if "SSH_PROXY_TEST_OK" in output:
            logger.info("✅ SSH PROXY TEST PASSED!")
            logger.info("   Output: %s", output)
        else:
            logger.warning("⚠️  SSH returned 0 but unexpected output: %s", output)
    else:
        logger.error("❌ SSH PROXY TEST FAILED (exit code %d)", proc.returncode)
        if stdout:
            logger.error("   stdout: %s", stdout.decode("utf-8", errors="replace").strip())
        if stderr:
            logger.error("   stderr: %s", stderr.decode("utf-8", errors="replace").strip())

    logger.info("─" * 60)
    logger.info("")

    # ── Cleanup ──
    logger.info("Cleaning up...")
    proxy_server.close()
    await proxy_server.wait_closed()
    await vm.stop()

    # Exit with proper code
    if proc.returncode != 0:
        sys.exit(1)
    if "SSH_PROXY_TEST_OK" not in (stdout or b"").decode("utf-8", errors="replace"):
        sys.exit(1)

    logger.info("Test complete. All good! 🎉")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
        sys.exit(1)
