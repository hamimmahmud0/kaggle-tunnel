# Kaggle Tunnel

This project builds a Windows desktop controller that:

- starts a local control server on the PC
- exposes that server with `cloudflared`
- copies notebook cell code with the live tunnel URL and token embedded
- lets the notebook connect back to the PC over websocket
- can forward TCP traffic through the notebook and expose a Python-based SSH server from the notebook

## Install

1. Install Python 3.11+.
2. Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python .\kaggle_tunnel_app.py
```

## Run A Local Script On Kaggle

After the tunnel is up, the notebook cell is running, and the local proxy has been started, you can upload a local Python file to the notebook and execute it over SSH with `run.py`.

Examples:

```powershell
python .\run.py .\your_script.py
python .\run.py .\your_script.py -- arg1 arg2
python .\run.py .\your_script.py --password "YOUR_SHARED_TOKEN"
```

Defaults used by `run.py`:

- SSH host: `127.0.0.1`
- SSH port: `10022`
- SSH user: `notebook`
- Remote upload directory: `/kaggle/working`

You can also override them if needed:

```powershell
python .\run.py .\your_script.py --host 127.0.0.1 --port 10022 --user notebook --remote-dir /kaggle/working
```

## Basic flow

1. Start the tunnel from the app.
2. Wait for the `trycloudflare.com` URL to appear.
3. Click `Copy Cell Code`.
4. Run the generated code on the remote notebook machine.
5. Start the local proxy.
6. SSH from the PC with `ssh -p 10022 notebook@127.0.0.1` and use the Shared token as the password.
7. If needed, click `Copy Agent Prompt` to copy an LLM-ready instruction block for connecting to this execution server.
8. Run `python .\run.py .\your_script.py` to upload and execute a local Python script on the notebook.

## Important note

The generated notebook helper is a long-running control agent. Keep that cell running while you use the desktop app.

The embedded SSH server now reuses a host key saved at `/kaggle/working/.kaggle_tunnel/ssh_host_key`, which helps avoid repeated host key warnings across notebook restarts in the same Kaggle workspace.

If you already connected before this change and see `REMOTE HOST IDENTIFICATION HAS CHANGED!` on Windows, remove the stale entry once with:

```powershell
ssh-keygen -R "[127.0.0.1]:10022"
```
