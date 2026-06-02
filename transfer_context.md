# Kaggle Tunnel — Transfer Context

## Project Overview

A desktop application and toolchain for connecting Kaggle notebooks back to a local machine via SSH through Cloudflare tunnels. Uses a **reversed-direction** architecture where the Kaggle VM (notebook) initiates outbound WebSocket connections through Cloudflare Tunnel, and the local PC connects to it via a TCP-to-WebSocket proxy.

## Architecture

```
Kaggle VM (notebook)                          Local PC
─────────────────────                         ────────
┌──────────────────────┐           ┌──────────────────────────┐
│  SSH server (:2222)  │           │  Proxy (:10022-20000)    │
│  WS proxy (:8765)    │◄─wss──────│  (TCP↔WS bridge)        │
│  cloudflared tunnel  │           │  Tauri Desktop App       │
│  tunnelbroker reg    │           │  GNOME Extension         │
└──────────────────────┘           └──────────────────────────┘
         │                                  │
         └────── tunnelbroker API ──────────┘
         (register/discover peers)
```

### Key Components

| Component | Path | Description |
|-----------|------|-------------|
| Notebook Cell | `src/kaggle_tunnel/notebook_cell.py` | Python template rendered into a Kaggle notebook cell. Starts SSH server + WS proxy + cloudflared + registers in tunnelbroker |
| Local Proxy | `src/kaggle_tunnel/proxy.py` | TCP-to-WebSocket bridge. Listens on local port, connects to VM's WS endpoint, forwards SSH traffic bidirectionally |
| Tunnelbroker Client | `src/kaggle_tunnel/tunnelbroker.py` | Python async+sync client for the tunnelbroker Cloudflare Worker API |
| Tauri App | `Kaggle Instance Manager/` | SvelteKit + Tauri v2 desktop app. Manages multiple VM instances, proxy lifecycle, SSH connections |
| GNOME Extension | `kgtun-gnome/` | GNOME 50 Shell extension showing instances in the panel |
| Test Suite | `scripts/test_proxy_local.py` | End-to-end test that simulates both VM and PC sides locally |

### Key Flows

#### 1. Notebook Cell (VM Side)

1. Starts `asyncssh` SSH server on port 2222 (password = first 10 alpha chars of group token)
2. Starts `aiohttp` WebSocket proxy on port 8765 (auth gate via `x-kaggle-tunnel-token` header)
3. Starts `cloudflared tunnel --url http://127.0.0.1:8765` to expose the WS proxy publicly
4. Registers in tunnelbroker: `POST /v1/peers?group=<group>` with endpoint, metadata, and secret
5. Keeps alive with periodic re-registration every 6 hours

#### 2. Proxy (PC Side)

1. Listens on a local TCP port (auto-assigned from 10022-20000)
2. On SSH connection: connects to VM's WS endpoint with auth token
3. Sends `tcp_open` → waits for `tcp_opened` → pumps data bidirectionally
4. Handles errors: token mismatch, VM down, connection timeout

#### 3. Peer Discovery

- VM registers: `POST /v1/peers?group=<group>` with `{peer, secret, endpoint, metadata}`
- PC discovers: `GET /v1/groups/<group>/peers` → returns peer list
- Tunnelbroker URL: `https://tunnelbroker.hamimmahmud0.workers.dev`

### Authentication

- **Group Token**: UUID used as bearer auth between PC and VM
- **SSH Password**: Derived from group token — first 10 alphabetic characters
- **WS Auth Gate**: VM's WSProxy checks `x-kaggle-tunnel-token` header matches `TUNNELBROKER_TOKEN`

## Build & Run

### Python Package

```bash
pip install -e .
```

### Tauri Desktop App

```bash
cd "Kaggle Instance Manager"
npm install
npm run tauri dev     # Development
npm run tauri build   # Production (.deb, .AppImage)
```

### GNOME Extension

```bash
cd kgtun-gnome
make install
# Then enable in GNOME Extensions app
```

### Test Proxy Locally

```bash
python3 scripts/test_proxy_local.py --token "test-token"
```

## Build Outputs

After `npm run tauri build`:
- `src-tauri/target/release/bundle/deb/kaggle-instance-manager_0.2.0_amd64.deb`
- `src-tauri/target/release/bundle/appimage/kaggle-instance-manager_0.2.0_amd64.AppImage`
- `src-tauri/target/release/kaggle-instance-manager` (binary)

## Key Config Files

| File | Purpose |
|------|---------|
| `snap/snapcraft.yaml` | Snap package config (needs LXD to build) |
| `Kaggle Instance Manager/src-tauri/tauri.conf.json` | Tauri app config, bundle settings |
| `Kaggle Instance Manager/src-tauri/Cargo.toml` | Rust dependencies |
| `pyproject.toml` | Python package config |
| `kgtun-gnome/schemas/org.gnome.shell.extensions.kgtun-manager.gschema.xml` | GNOME extension settings |

## Debugging

- Proxy logs (when started by app): `/tmp/kgl-proxy-logs/{peer_id}.log`
- Manual proxy: `python3 -m kaggle_tunnel.proxy --tunnel-url wss://.../ws --token <token> --local-port 10022 -v`
- Notebook cell output: visible in Kaggle notebook below the cell

## Important Notes

- The tunnel URL from tunnelbroker is the raw cloudflare URL (e.g., `https://xxx.trycloudflare.com`). The proxy automatically appends `/ws` and converts to `wss://`.
- The proxy auto-assigns ports starting from 10022 to avoid conflicts when running multiple instances.
- SSH commands use `sshpass` with the derived password; the "Copy SSH command" button gets the actual port from the running proxy.
