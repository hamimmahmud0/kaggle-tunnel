"""Local SSH proxy for the reversed-direction tunnel flow.

Connects to a VM's tunnel URL via WebSocket (authenticated with the
group token), listens on a local TCP port, and forwards SSH traffic
bidirectionally.

Usage::

    python -m kaggle_tunnel.proxy \\
        --tunnel-url wss://abc.trycloudflare.com/ws \\
        --token my-group-token \\
        --local-port 10022
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging

logger = logging.getLogger("kgl-proxy")


async def proxy_loop(
    tunnel_url: str,
    group_token: str,
    local_port: int,
    ssh_port: int = 2222,
) -> None:
    """Connect to the VM's WS tunnel and proxy SSH traffic."""
    import aiohttp

    # Ensure the tunnel URL points to the WebSocket endpoint
    if not tunnel_url.endswith("/ws"):
        tunnel_url = tunnel_url.rstrip("/") + "/ws"
    # Normalize scheme: https:// → wss:// (cosmetic, aiohttp handles both)
    tunnel_url = tunnel_url.replace("http://", "ws://").replace("https://", "wss://")

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        conn_id = f"ssh-{id(reader)}"
        peer = writer.get_extra_info("peername", ("?", 0))
        logger.info("[%s] New SSH client from %s:%d", conn_id, peer[0], peer[1])
        headers = {"x-kaggle-tunnel-token": group_token}
        try:
            logger.debug("[%s] Connecting to WS %s ...", conn_id, tunnel_url)
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.ws_connect(
                    tunnel_url, max_msg_size=0, heartbeat=20.0
                ) as ws:
                    logger.info("[%s] WS connected to %s", conn_id, tunnel_url)
                    logger.debug("[%s] Sending tcp_open (host=127.0.0.1 port=%d)", conn_id, ssh_port)
                    await ws.send_json({
                        "type": "tcp_open",
                        "connection_id": conn_id,
                        "host": "127.0.0.1",
                        "port": ssh_port,
                    })

                    # Wait for VM to confirm TCP connection opened
                    confirmed = False
                    ws_closed_by_vm = False
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            payload = json.loads(msg.data)
                            ptype = payload.get("type")
                            if ptype == "tcp_opened" and payload.get("connection_id") == conn_id:
                                logger.info("[%s] VM confirmed TCP opened ✓", conn_id)
                                confirmed = True
                                break
                            elif ptype == "tcp_closed" and payload.get("connection_id") == conn_id:
                                err = payload.get("error", "unknown error")
                                logger.error("[%s] VM TCP closed: %s", conn_id, err)
                                raise ConnectionError(f"VM TCP proxy failed: {err}")
                            elif ptype == "hello":
                                logger.info("[%s] VM hello: name=%s host=%s ssh_port=%s",
                                    conn_id,
                                    payload.get("instance_name", "?"),
                                    payload.get("hostname", "?"),
                                    payload.get("ssh_port", "?"))
                            elif ptype == "error":
                                err_msg = payload.get("message", "unknown")
                                logger.error("[%s] VM returned error: %s", conn_id, err_msg)
                                raise PermissionError(f"VM rejected connection: {err_msg}")
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            ws_closed_by_vm = True
                            logger.warning("[%s] VM closed WebSocket (code=%s) during TCP open wait",
                                conn_id, msg.data or "none")
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.warning("[%s] WS error during TCP open wait: %s",
                                conn_id, ws.exception() or "unknown")
                            break
                    if not confirmed:
                        if ws_closed_by_vm:
                            logger.error("[%s] VM closed WebSocket without confirming TCP — likely TOKEN MISMATCH or VM SSH server down", conn_id)
                            raise ConnectionError("VM closed WebSocket without confirming TCP — check that the group token is correct and the VM SSH server is running")
                        else:
                            logger.error("[%s] VM did not respond with tcp_opened (connection timed out)", conn_id)
                            raise TimeoutError("VM did not respond to tcp_open request")

                    # ── Data pump: SSH → WS ──
                    bytes_to_vm = 0
                    bytes_from_vm = 0

                    async def pump_to_ws():
                        nonlocal bytes_to_vm
                        try:
                            while True:
                                chunk = await reader.read(65536)
                                if not chunk:
                                    logger.debug("[%s] SSH client EOF", conn_id)
                                    break
                                bytes_to_vm += len(chunk)
                                logger.debug("[%s] SSH→WS %d bytes (total %d)", conn_id, len(chunk), bytes_to_vm)
                                await ws.send_json({
                                    "type": "tcp_data",
                                    "connection_id": conn_id,
                                    "data": base64.b64encode(chunk).decode("ascii"),
                                })
                        except Exception as exc:
                            logger.debug("[%s] pump_to_ws exception: %s", conn_id, exc)
                        finally:
                            logger.info("[%s] pump_to_ws done, sent %d bytes to VM", conn_id, bytes_to_vm)
                            try:
                                await ws.send_json({
                                    "type": "tcp_close",
                                    "connection_id": conn_id,
                                })
                            except Exception as exc:
                                logger.debug("[%s] tcp_close send failed: %s", conn_id, exc)

                    pump_task = asyncio.create_task(pump_to_ws())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                payload = json.loads(msg.data)
                                ptype = payload.get("type")
                                if ptype == "tcp_data" and payload.get("connection_id") == conn_id:
                                    data = base64.b64decode(payload["data"])
                                    bytes_from_vm += len(data)
                                    logger.debug("[%s] WS→SSH %d bytes (total %d)", conn_id, len(data), bytes_from_vm)
                                    writer.write(data)
                                    await writer.drain()
                                elif ptype == "tcp_closed" and payload.get("connection_id") == conn_id:
                                    err = payload.get("error")
                                    if err:
                                        logger.info("[%s] VM closed TCP: %s", conn_id, err)
                                    else:
                                        logger.info("[%s] VM closed TCP (clean)", conn_id)
                                    break
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                                logger.warning("[%s] WS error/close during data pump: %s",
                                    conn_id, ws.exception() or "closed")
                                break
                    finally:
                        pump_task.cancel()
                        try:
                            await pump_task
                        except asyncio.CancelledError:
                            pass
                        logger.info("[%s] Proxy session ended: ↑%d bytes to VM, ↓%d bytes from VM",
                            conn_id, bytes_to_vm, bytes_from_vm)

        except (OSError, ConnectionError, TimeoutError, PermissionError, aiohttp.WSServerHandshakeError) as exc:
            logger.error("[%s] Connection error: %s", conn_id, exc)
            err_msg = f"Proxy error: {exc}\n".encode()
            try:
                writer.write(err_msg)
                await writer.drain()
            except Exception:
                pass
        except Exception as exc:
            logger.exception("[%s] Unexpected proxy error", conn_id)
            err_msg = f"Proxy error: {exc}\n".encode()
            try:
                writer.write(err_msg)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                logger.debug("[%s] SSH client writer closed", conn_id)
            except Exception as exc:
                logger.debug("[%s] Failed to close writer: %s", conn_id, exc)

    server = await asyncio.start_server(handle_client, "127.0.0.1", local_port)
    logger.info(
        "Proxy on 127.0.0.1:%d -> %s (SSH :%d)", local_port, tunnel_url, ssh_port
    )
    try:
        await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        server.close()
        await server.wait_closed()


async def main() -> None:
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    parser = argparse.ArgumentParser(description="Kaggle Tunnel local SSH proxy")
    parser.add_argument("--tunnel-url", help="WS tunnel URL (or use --config)")
    parser.add_argument("--token", help="Group bearer token")
    parser.add_argument("--local-port", type=int, default=10022, help="Local TCP port")
    parser.add_argument("--ssh-port", type=int, default=2222, help="VM SSH port")
    parser.add_argument("--config", help="Path to manager config JSON (reads tunnelbroker settings)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    tunnel_url = args.tunnel_url
    token = args.token

    # If config file provided, read tunnelbroker settings from it
    if args.config:
        cfg_path = _Path(args.config).expanduser().resolve()
        if cfg_path.exists():
            try:
                cfg = _json.loads(cfg_path.read_text())
                if not tunnel_url and cfg.get("known_instances"):
                    # Pick the first online instance's endpoint
                    for inst in cfg["known_instances"].values():
                        if inst.get("endpoint"):
                            tunnel_url = inst["endpoint"]
                            break
                if not token:
                    token = cfg.get("tunnelbroker_token", "")
                logger.info("Read config from %s", cfg_path)
            except Exception as e:
                logger.warning("Failed to read config: %s", e)

    if not tunnel_url:
        parser.error("--tunnel-url is required (or use --config with a configured instance)")
    if not token:
        parser.error("--token is required (or use --config)")

    await proxy_loop(tunnel_url, token, args.local_port, args.ssh_port)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
