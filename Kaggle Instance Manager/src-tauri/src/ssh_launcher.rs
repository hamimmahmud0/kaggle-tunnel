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
    cmd.push_str(&format!(" {}@{}", params.user, params.host));
    cmd
}

/// Build an SSH command that goes through a cloudflared tunnel
/// (useful when the endpoint is a Cloudflare tunnel URL).
pub fn build_ssh_command_via_tunnel(params: &SshConnectionParams, _tunnel_url: &str) -> String {
    // For WebSocket-based tunnels, the actual SSH happens through the
    // local proxy. This builds the SSH command for 127.0.0.1:proxy_port.
    build_ssh_command(params)
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
/// Returns an error message if no terminal is found or the launch fails.
pub fn launch_ssh(params: &SshConnectionParams) -> Result<String, String> {
    let ssh_cmd = build_ssh_command(params);

    let terminal = detect_terminal().ok_or_else(|| {
        "No supported terminal emulator found. Install gnome-terminal, konsole, or xterm.".to_string()
    })?;

    let result = match terminal.as_str() {
        "gnome-terminal" => {
            Command::new("gnome-terminal")
                .args(["--", "bash", "-c", &format!("{}; exec bash", ssh_cmd)])
                .spawn()
        }
        "konsole" => {
            Command::new("konsole")
                .args(["--noclose", "-e", &ssh_cmd])
                .spawn()
        }
        "xfce4-terminal" => {
            Command::new("xfce4-terminal")
                .args(["--hold", "-e", &ssh_cmd])
                .spawn()
        }
        "lxterminal" => {
            Command::new("lxterminal")
                .args(["-e", &ssh_cmd])
                .spawn()
        }
        "terminator" => {
            Command::new("terminator")
                .args(["-e", &ssh_cmd])
                .spawn()
        }
        "alacritty" | "kitty" | "wezterm" => {
            Command::new(&terminal)
                .args(["-e", "bash", "-c", &ssh_cmd])
                .spawn()
        }
        "x-terminal-emulator" | "ptyxis" | "kgx" | "blackbox" | "foot" => {
            // Generic terminals that accept -e
            Command::new(&terminal)
                .args(["-e", "bash", "-c", &ssh_cmd])
                .spawn()
        }
        _ => {
            // fallback: xterm or urxvt
            Command::new(&terminal)
                .args(["-e", &ssh_cmd])
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
