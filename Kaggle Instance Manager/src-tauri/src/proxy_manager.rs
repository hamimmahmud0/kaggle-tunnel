//! Manages per-instance proxy processes with auto-assigned ports.

use std::collections::HashMap;
use std::fs::{self, File};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

#[derive(Debug, Clone)]
pub struct ProxyInfo {
    pub pid: u32,
    pub local_port: u16,
    pub status: ProxyStatus,
}

#[derive(Debug, Clone, PartialEq)]
pub enum ProxyStatus {
    Starting,
    Running,
    Stopped,
    Error(String),
}

/// Directory where per-instance proxy logs are written.
fn log_dir() -> std::path::PathBuf {
    let dir = std::path::PathBuf::from("/tmp/kgl-proxy-logs");
    let _ = fs::create_dir_all(&dir);
    dir
}

/// Try to find the bundled `kaggle_tunnel` Python package relative to the binary.
/// Returns the parent directory to add to `PYTHONPATH`, or `None` if not bundled.
pub(crate) fn find_bundled_kaggle_tunnel() -> Option<std::path::PathBuf> {
    // 1. Environment variable override (used by Snap or manual configs)
    if let Ok(path) = std::env::var("KAGGLE_TUNNEL_PYTHONPATH") {
        let p = std::path::PathBuf::from(&path);
        if p.join("kaggle_tunnel").join("proxy.py").exists() {
            return Some(p);
        }
    }

    // 2. Resolve relative to the current executable
    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            // Typical .deb layout:
            //   binary -> /usr/bin/kaggle-instance-manager
            //   resources -> /usr/lib/kaggle-instance-manager/resources/kaggle_tunnel/
            let candidates = [
                exe_dir.join("../lib/kaggle-instance-manager/resources"),
                exe_dir.join("../resources"),
                exe_dir.join("resources"),
            ];
            for candidate in &candidates {
                if candidate.join("kaggle_tunnel").join("proxy.py").exists() {
                    return Some(candidate.clone());
                }
            }
        }
    }

    None
}

pub struct ProxyManager {
    proxies: Mutex<HashMap<String, ProxyInfo>>,
}

impl ProxyManager {
    pub fn new() -> Self {
        Self {
            proxies: Mutex::new(HashMap::new()),
        }
    }

    fn find_free_port(&self, start: u16) -> Option<u16> {
        for port in start..=20000 {
            if std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
                return Some(port);
            }
        }
        None
    }

    pub fn start(
        &self,
        peer_id: &str,
        tunnel_url: &str,
        token: &str,
        ssh_user: &str,
        password: &str,
    ) -> Result<ProxyInfo, String> {
        // Stop any existing proxy for this peer
        let _ = self.stop(peer_id);

        let local_port = self
            .find_free_port(10022)
            .ok_or_else(|| "No free port found in range 10022-20000".to_string())?;

        let python =
            std::env::var("KAGGLE_TUNNEL_PYTHON").unwrap_or_else(|_| "python3".to_string());

        // Redirect stderr to a log file so we can debug crashes
        let log_path = log_dir().join(format!("{}.log", peer_id));
        let log_file = File::create(&log_path)
            .map_err(|e| format!("Failed to create log file {}: {}", log_path.display(), e))?;

        // Build the command with PYTHONPATH if bundled resources are found
        let mut cmd = Command::new(&python);
        if let Some(bundled_path) = find_bundled_kaggle_tunnel() {
            let existing_path = std::env::var("PYTHONPATH").unwrap_or_default();
            let new_path = if existing_path.is_empty() {
                bundled_path.to_string_lossy().to_string()
            } else {
                format!("{}:{}", bundled_path.to_string_lossy(), existing_path)
            };
            cmd.env("PYTHONPATH", new_path);
        }

        let mut child = cmd
            .args([
                "-m",
                "kaggle_tunnel.proxy",
                "--tunnel-url",
                tunnel_url,
                "--token",
                token,
                "--local-port",
                &local_port.to_string(),
                "--ssh-port",
                "2222",
                "-v",
            ])
            .stdout(Stdio::null())
            .stderr(log_file)
            .spawn()
            .map_err(|e| format!("Failed to start proxy: {}", e))?;

        let pid = child.id();
        // Detach — don't wait for the child
        std::thread::spawn(move || {
            let _ = child.wait();
        });

        // Wait briefly for proxy to bind
        std::thread::sleep(std::time::Duration::from_millis(500));

        let mut proxies = self.proxies.lock().map_err(|e| e.to_string())?;
        let info = ProxyInfo {
            pid,
            local_port,
            status: ProxyStatus::Running,
        };
        proxies.insert(peer_id.to_string(), info.clone());
        Ok(info)
    }

    pub fn stop(&self, peer_id: &str) -> Result<(), String> {
        let mut proxies = self.proxies.lock().map_err(|e| e.to_string())?;
        if let Some(info) = proxies.remove(peer_id) {
            let _ = Command::new("kill")
                .args(["-9", &info.pid.to_string()])
                .output();
            let _ = Command::new("sh")
                .args(["-c", &format!("fuser -k {}/tcp 2>/dev/null", info.local_port)])
                .output();
        }
        Ok(())
    }

    pub fn get(&self, peer_id: &str) -> Option<ProxyInfo> {
        self.proxies.lock().ok().and_then(|p| p.get(peer_id).cloned())
    }

    pub fn stop_all(&self) {
        let ids: Vec<String> = self
            .proxies
            .lock()
            .map(|p| p.keys().cloned().collect())
            .unwrap_or_default();
        for id in &ids {
            let _ = self.stop(id);
        }
    }
}
