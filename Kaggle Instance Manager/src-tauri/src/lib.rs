mod instance_manager;
mod namegen;
mod proxy_manager;
mod ssh_launcher;
mod tunnelbroker;

use instance_manager::{InstanceManager, InstanceState, ManagerConfig};
use proxy_manager::ProxyInfo;
use ssh_launcher::SshConnectionParams;
use std::process::{Command, Stdio};
use std::sync::Mutex;
use tauri::State;

// ── Helpers ───────────────────────────────────────────────────────────

/// Derive SSH password from the group token: first 10 alphabetic chars.
fn first_10_alpha(s: &str) -> String {
    s.chars().filter(|c| c.is_ascii_alphabetic()).take(10).collect()
}

// ── Shared state ──────────────────────────────────────────────────────

struct AppState {
    manager: Mutex<InstanceManager>,
    proxy_manager: proxy_manager::ProxyManager,
}

// ── Tauri commands ────────────────────────────────────────────────────

/// List all known instances (from local cache).
#[tauri::command]
fn list_instances(state: State<'_, AppState>) -> Result<Vec<InstanceState>, String> {
    let config = state.manager.lock().map_err(|e| e.to_string())?.get_config()?;
    let mut instances: Vec<InstanceState> = config
        .known_instances
        .into_values()
        .collect();
    instances.sort_by(|a, b| a.label.cmp(&b.label));
    Ok(instances)
}

/// Fetch live instances from tunnelbroker and sync to local cache.
#[tauri::command]
async fn refresh_instances(
    state: State<'_, AppState>,
) -> Result<Vec<InstanceState>, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    if config.tunnelbroker_url.is_empty() {
        return Err("Tunnelbroker URL not configured. Go to Settings first.".to_string());
    }

    let client = tunnelbroker::TunnelbrokerClient::new(
        &config.tunnelbroker_url,
        &config.tunnelbroker_group,
        config.tunnelbroker_token.clone(),
    );

    let peers = client.list_peers().await?;

    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    manager.sync_from_peers(&peers)
}

/// Get credentials for a specific instance (fetches from tunnelbroker).
#[tauri::command]
async fn get_instance_credentials(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<InstanceCredentials, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    if config.tunnelbroker_url.is_empty() {
        return Err("Tunnelbroker not configured".to_string());
    }

    let client = tunnelbroker::TunnelbrokerClient::new(
        &config.tunnelbroker_url,
        &config.tunnelbroker_group,
        config.tunnelbroker_token.clone(),
    );

    let peer = client.get_peer(&peer_id).await?;

    let endpoint = peer.endpoint.clone().or_else(|| {
        peer.contacts.first().map(|c| c.endpoint.clone())
    }).unwrap_or_default();

    let hostname = peer.metadata.get("hostname")
        .and_then(|v| v.as_str()).unwrap_or("unknown");
    let ssh_user = peer.metadata.get("ssh_user")
        .and_then(|v| v.as_str()).unwrap_or("notebook");
    let ssh_port = peer.metadata.get("ssh_port")
        .and_then(|v| v.as_u64()).unwrap_or(2222) as u16;
    let fingerprint = peer.metadata.get("ssh_host_key_fingerprint")
        .and_then(|v| v.as_str()).unwrap_or("");

    Ok(InstanceCredentials {
        peer_id: peer.peer.clone(),
        instance_name: peer.metadata.get("instance_name")
            .and_then(|v| v.as_str()).unwrap_or(&peer.peer).to_string(),
        hostname: hostname.to_string(),
        ssh_user: ssh_user.to_string(),
        ssh_port,
        endpoint: endpoint.clone(),
        fingerprint: fingerprint.to_string(),
        // The secret is only available on the instance side, not exposed
        // by tunnelbroker's list/get. We cache it separately if provided.
        shared_secret: String::new(),
        tunnel_endpoint: endpoint,
    })
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct InstanceCredentials {
    pub peer_id: String,
    pub instance_name: String,
    pub hostname: String,
    pub ssh_user: String,
    pub ssh_port: u16,
    pub endpoint: String,
    pub fingerprint: String,
    pub shared_secret: String,
    pub tunnel_endpoint: String,
}

/// Launch SSH connection in system terminal.
#[tauri::command]
fn ssh_connect(peer_id: String, state: State<'_, AppState>) -> Result<String, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    let instance = config.known_instances.get(&peer_id).ok_or_else(|| {
        format!("Instance '{}' not found", peer_id)
    })?;

    let host = instance.endpoint.clone().unwrap_or_else(|| "127.0.0.1".to_string());
    let user = instance.ssh_user.clone().unwrap_or_else(|| "notebook".to_string());
    let port = instance.ssh_port.unwrap_or(22);

    let params = SshConnectionParams {
        user,
        host,
        port,
        password: instance.shared_secret.clone(),
        fingerprint: instance.fingerprint.clone(),
    };

    ssh_launcher::launch_ssh(&params)
}

/// Get current tunnelbroker configuration.
#[tauri::command]
fn get_config(state: State<'_, AppState>) -> Result<ManagerConfig, String> {
    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    manager.get_config()
}

/// Update tunnelbroker configuration.
#[tauri::command]
fn set_config(config: ManagerConfig, state: State<'_, AppState>) -> Result<(), String> {
    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    manager.set_config(config)
}

/// Set just the tunnelbroker connection settings.
#[tauri::command]
fn set_tunnelbroker_config(
    url: String,
    group: String,
    token: Option<String>,
    state: State<'_, AppState>,
) -> Result<(), String> {
    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    manager.set_tunnelbroker_config(&url, &group, token)
}

/// Regenerate the group token with a new UUID.
#[tauri::command]
fn regenerate_token(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    let new_token = uuid::Uuid::new_v4().to_string();
    let mut config = manager.get_config()?;
    config.tunnelbroker_token = Some(new_token.clone());
    // Regenerate group name with Reddit-style auto-name
    let new_group = namegen::generate();
    config.tunnelbroker_group = new_group.clone();
    manager.set_config(config)?;
    let result = serde_json::json!({
        "token": new_token,
        "group": new_group,
    });
    Ok(result.to_string())
}

/// Remove an instance from the local cache.
#[tauri::command]
fn remove_instance(peer_id: String, state: State<'_, AppState>) -> Result<(), String> {
    let manager = state.manager.lock().map_err(|e| e.to_string())?;
    manager.remove_instance(&peer_id)
}

/// Build the SSH command string for display (without launching).
#[tauri::command]
fn build_ssh_command(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    let instance = config.known_instances.get(&peer_id).ok_or_else(|| {
        format!("Instance '{}' not found", peer_id)
    })?;

    let host = instance.endpoint.clone().unwrap_or_else(|| "127.0.0.1".to_string());
    let user = instance.ssh_user.clone().unwrap_or_else(|| "notebook".to_string());
    let port = instance.ssh_port.unwrap_or(22);

    let params = SshConnectionParams { user, host, port, password: None, fingerprint: None };
    Ok(ssh_launcher::build_ssh_command(&params))
}

/// Deregister an instance — removes from local cache and attempts to
/// delete the peer record from tunnelbroker.
#[tauri::command]
async fn deregister_peer(peer_id: String, state: State<'_, AppState>) -> Result<String, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    if !config.tunnelbroker_url.is_empty() {
        let client = tunnelbroker::TunnelbrokerClient::new(
            &config.tunnelbroker_url,
            &config.tunnelbroker_group,
            config.tunnelbroker_token.clone(),
        );
        let _ = client.delete_peer(&peer_id, "").await;
    }

    {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.remove_instance(&peer_id)?;
    }
    Ok(format!("Instance '{}' deregistered", peer_id))
}

/// Build SSH command including password for easy copy-paste.
/// Password is derived from the group token (first 10 alpha chars).
/// Port comes from the running proxy (or falls back to 10022).
#[tauri::command]
fn build_ssh_command_with_password(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    let instance = config.known_instances.get(&peer_id).ok_or_else(|| {
        format!("Instance '{}' not found", peer_id)
    })?;

    let user = instance.ssh_user.clone().unwrap_or_else(|| "notebook".to_string());
    let password = first_10_alpha(&config.tunnelbroker_token.unwrap_or_default());

    // Get the actual proxy port from proxy_manager
    let proxy_port = state.proxy_manager.get(&peer_id)
        .map(|info| info.local_port)
        .unwrap_or(10022);

    Ok(format!(
        "sshpass -p '{}' ssh -o StrictHostKeyChecking=accept-new -p {} {}@127.0.0.1",
        password, proxy_port, user
    ))
}

/// Generate a random Reddit-style instance name (e.g. ``QuietFox_7291``).
#[tauri::command]
fn generate_instance_name() -> String {
    namegen::generate()
}

/// Generate notebook cell code and return it (frontend copies to clipboard).
#[tauri::command]
fn generate_cell_code(
    instance_name: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    // Derive SSH password from the group token (first 10 alpha chars)
    // so both sides know it without exchanging secrets.
    let shared_secret = first_10_alpha(&config.tunnelbroker_token.as_ref().map(|s| s.as_str()).unwrap_or(""));

    let python = std::env::var("KAGGLE_TUNNEL_PYTHON").unwrap_or_else(|_| "python3".to_string());
    let script = format!(
        r#"from kaggle_tunnel.app import generate_tunnelbroker_cell_code; \
print(generate_tunnelbroker_cell_code(\
    instance_name={:?},\
    tunnelbroker_url={:?},\
    tunnelbroker_group={:?},\
    tunnelbroker_token={:?},\
    shared_secret={:?}))"#,
        instance_name,
        config.tunnelbroker_url,
        config.tunnelbroker_group,
        config.tunnelbroker_token.unwrap_or_default(),
        shared_secret,
    );

    let output = Command::new(&python)
        .args(["-c", &script])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("Failed to run Python: {}", e))?;

    if !output.status.success() {
        let err = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Python error: {}", err));
    }
    let cell = String::from_utf8_lossy(&output.stdout).to_string();

    let result = serde_json::json!({
        "cell": cell.trim(),
        "shared_secret": shared_secret,
    });
    Ok(result.to_string())
}

/// Connect SSH via local proxy — launches Python proxy then terminal.
/// Password is derived from the group token.
/// Uses the already-running proxy from proxy_manager if available.
#[tauri::command]
fn ssh_connect_proxy(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<String, String> {
    // Check if proxy is already running for this peer
    let proxy_info = state.proxy_manager.get(&peer_id)
        .ok_or_else(|| format!("No proxy running for instance '{}' — start proxy first", peer_id))?;

    let local_port = proxy_info.local_port;
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    let instance = config.known_instances.get(&peer_id).ok_or_else(|| {
        format!("Instance '{}' not found", peer_id)
    })?;

    let ssh_user = instance.ssh_user.clone().unwrap_or_else(|| "notebook".to_string());
    let password = first_10_alpha(&config.tunnelbroker_token.unwrap_or_default());

    let params = SshConnectionParams {
        user: ssh_user,
        host: "127.0.0.1".to_string(),
        port: local_port,
        password: Some(password),
        fingerprint: instance.fingerprint.clone(),
    };

    // Spawn terminal in background thread so we don't block the UI
    std::thread::spawn(move || {
        let _ = ssh_launcher::launch_ssh(&params);
    });

    Ok(format!("SSH terminal launched on port {}", local_port))
}

// ── Proxy management commands ─────────────────────────────────────────

#[derive(serde::Serialize)]
struct ProxyInfoJson {
    pid: u32,
    local_port: u16,
    status: String,
}

#[tauri::command]
fn start_instance_proxy(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<ProxyInfoJson, String> {
    let config = {
        let manager = state.manager.lock().map_err(|e| e.to_string())?;
        manager.get_config()?
    };

    let instance = config.known_instances.get(&peer_id).ok_or_else(|| {
        format!("Instance '{}' not found", peer_id)
    })?;

    let tunnel_url = instance.endpoint.clone().unwrap_or_default();
    if tunnel_url.is_empty() {
        return Err("Instance has no tunnel endpoint".to_string());
    }
    let token = config.tunnelbroker_token.unwrap_or_default();
    let ssh_user = instance.ssh_user.clone().unwrap_or_else(|| "notebook".to_string());
    let password = first_10_alpha(&token);

    let info = state.proxy_manager.start(&peer_id, &tunnel_url, &token, &ssh_user, &password)?;
    Ok(ProxyInfoJson {
        pid: info.pid,
        local_port: info.local_port,
        status: format!("{:?}", info.status),
    })
}

#[tauri::command]
fn stop_instance_proxy(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.proxy_manager.stop(&peer_id)
}

#[tauri::command]
fn get_instance_proxy_status(
    peer_id: String,
    state: State<'_, AppState>,
) -> Result<Option<ProxyInfoJson>, String> {
    Ok(state.proxy_manager.get(&peer_id).map(|info| ProxyInfoJson {
        pid: info.pid,
        local_port: info.local_port,
        status: format!("{:?}", info.status),
    }))
}

// ── Application entry point ───────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app_state = AppState {
        manager: Mutex::new(InstanceManager::new()),
        proxy_manager: proxy_manager::ProxyManager::new(),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            list_instances,
            refresh_instances,
            get_instance_credentials,
            ssh_connect,
            get_config,
            set_config,
            set_tunnelbroker_config,
            regenerate_token,
            remove_instance,
            build_ssh_command,
            build_ssh_command_with_password,
            deregister_peer,
            generate_cell_code,
            generate_instance_name,
            ssh_connect_proxy,
            start_instance_proxy,
            stop_instance_proxy,
            get_instance_proxy_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
