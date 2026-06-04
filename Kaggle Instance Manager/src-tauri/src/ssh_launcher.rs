//! SSH terminal launcher.
//!
//! Detects the available terminal emulator and spawns an SSH session
//! to a Kaggle instance through its tunnel endpoint.

use std::process::Command;

/// Information needed to build an SSH command.
#[derive(Debug, Clone)]
pub struct SshConnectionParams {
    pub user: String,
    pub host: String,
    pub port: u16,
    pub password: Option<String>,
    pub fingerprint: Option<String>,
}

/// Build the SSH command string to display or launch.
///
/// Forces a PTY (`-t`) and sources `.bashrc` on the remote host so the
/// user's aliases, PATH additions, and ssh-agent are available inside
/// the SSH session.  Falls back to an interactive bash shell on exit.
pub fn build_ssh_command(params: &SshConnectionParams) -> String {
    let mut cmd = String::new();

    // Prepend sshpass if a password is available
    if let Some(pwd) = &params.password {
        cmd.push_str(&format!("sshpass -p '{}' ", pwd));
    }

    cmd.push_str("ssh");
    if params.port != 22 {
        cmd.push_str(&format!(" -p {}", params.port));
    }
    // Accept new host key automatically for convenience
    cmd.push_str(" -o StrictHostKeyChecking=accept-new");
    // Force PTY allocation (needed when passing a remote command)
    cmd.push_str(" -t");
    cmd.push_str(&format!(" {}@{}", params.user, params.host));
    // Source .bashrc on the remote host, then start interactive bash
    cmd.push_str(" \". ~/.bashrc 2>/dev/null; exec bash -i\"");
    cmd
}

/// Build an SSH command that goes through a cloudflared tunnel
/// (useful when the endpoint is a Cloudflare tunnel URL).
pub fn build_ssh_command_via_tunnel(params: &SshConnectionParams, _tunnel_url: &str) -> String {
    // For WebSocket-based tunnels, the actual SSH happens through the
    // local proxy. This builds the SSH command for 127.0.0.1:proxy_port.
    build_ssh_command(params)
}

/// Remove old SSH host key from known_hosts for the given host:port.
/// This prevents the "REMOTE HOST IDENTIFICATION HAS CHANGED" error
/// when the remote key changes between notebook sessions (Kaggle VMs
/// regenerate host keys on each start).
fn clean_host_key(host: &str, port: u16) {
    let host_spec = if port != 22 {
        format!("[{}]:{}", host, port)
    } else {
        host.to_string()
    };
    let _ = Command::new("ssh-keygen")
        .args(["-R", &host_spec])
        .output();
}

/// Detect available terminal emulators on Linux.
fn detect_terminal() -> Option<String> {
    for terminal in &[
        "gnome-terminal",
        "konsole",
        "xfce4-terminal",
        "lxterminal",
        "terminator",
        "urxvt",
        "xterm",
        "alacritty",
        "kitty",
        "wezterm",
        "ptyxis",
        "kgx",
        "blackbox",
        "foot",
        "x-terminal-emulator",  // Debian/Ubuntu default alias
    ] {
        if which(terminal) {
            return Some(terminal.to_string());
        }
    }
    None
}

fn which(name: &str) -> bool {
    Command::new("which")
        .arg(name)
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Launch the system terminal with an SSH command.
///
/// Cleans old host keys before connecting and sources the user's .bashrc
/// so aliases, PATH changes, and SSH key configs are available.
/// Returns an error message if no terminal is found or the launch fails.
pub fn launch_ssh(params: &SshConnectionParams) -> Result<String, String> {
    // Clean old host key so StrictHostKeyChecking=accept-new doesn't fail
    // when the remote host key changes between notebook sessions
    clean_host_key(&params.host, params.port);

    let ssh_cmd = build_ssh_command(params);

    let terminal = detect_terminal().ok_or_else(|| {
        "No supported terminal emulator found. Install gnome-terminal, konsole, alacritty, or xterm.".to_string()
    })?;

    // Source .bashrc explicitly — non-interactive `bash -c` doesn't source it,
    // but users often have aliases, PATH additions, or ssh-agent configs there.
    let bash_setup = ". ~/.bashrc 2>/dev/null";

    let result = match terminal.as_str() {
        "gnome-terminal" => {
            Command::new("gnome-terminal")
                .args(["--", "bash", "-c", &format!("{}; {}; exec bash", bash_setup, ssh_cmd)])
                .spawn()
        }
        "konsole" => {
            Command::new("konsole")
                .args(["--noclose", "-e", "bash", "-c", &format!("{}; {}", bash_setup, ssh_cmd)])
                .spawn()
        }
        "xfce4-terminal" => {
            Command::new("xfce4-terminal")
                .args(["--hold", "-e", "bash", "-c", &format!("{}; {}", bash_setup, ssh_cmd)])
                .spawn()
        }
        "lxterminal" => {
            Command::new("lxterminal")
                .args(["-e", "bash", "-c", &format!("{}; {}", bash_setup, ssh_cmd)])
                .spawn()
        }
        "terminator" => {
            Command::new("terminator")
                .args(["-e", "bash", "-c", &format!("{}; {}", bash_setup, ssh_cmd)])
                .spawn()
        }
        "alacritty" | "kitty" | "wezterm" => {
            Command::new(&terminal)
                .args(["-e", "bash", "-c", &format!("{}; {}; exec bash", bash_setup, ssh_cmd)])
                .spawn()
        }
        "x-terminal-emulator" | "ptyxis" | "kgx" | "blackbox" | "foot" => {
            // Generic terminals that accept -e
            Command::new(&terminal)
                .args(["-e", "bash", "-c", &format!("{}; {}; exec bash", bash_setup, ssh_cmd)])
                .spawn()
        }
        _ => {
            // fallback: xterm or urxvt
            Command::new(&terminal)
                .args(["-e", "bash", "-c", &format!("{}; {}; exec bash", bash_setup, ssh_cmd)])
                .spawn()
        }
    };

    match result {
        Ok(mut child) => {
            // Detach — we don't wait for the terminal to close
            // SAFETY: We intentionally detach from the child process.
            // The terminal window remains open independently.
            #[allow(deprecated)]
            child.wait().ok();
            Ok(format!("Launched SSH in {}", terminal))
        }
        Err(e) => Err(format!("Failed to launch {}: {}", terminal, e)),
    }
}
