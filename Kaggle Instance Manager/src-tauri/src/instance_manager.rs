//! Local instance state management.
//!
//! Tracks known instances, caches tunnelbroker data, and persists
//! configuration to disk.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Mutex;
use serde::{Deserialize, Serialize};

/// Configuration persisted to disk.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManagerConfig {
    pub tunnelbroker_url: String,
    pub tunnelbroker_group: String,
    #[serde(default)]
    pub tunnelbroker_token: Option<String>,
    #[serde(default)]
    pub cloudflared_path: Option<String>,
    #[serde(default)]
    pub known_instances: HashMap<String, InstanceState>,
}

impl Default for ManagerConfig {
    fn default() -> Self {
        Self {
            tunnelbroker_url: "https://tunnelbroker.hamimmahmud0.workers.dev".to_string(),
            tunnelbroker_group: "default".to_string(),
            tunnelbroker_token: None,
            cloudflared_path: None,
            known_instances: HashMap::new(),
        }
    }
}

/// Local state for a single instance (cached from tunnelbroker).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstanceState {
    pub peer_id: String,
    pub label: String,
    pub status: InstanceStatus,
    pub hostname: Option<String>,
    pub ssh_user: Option<String>,
    pub ssh_port: Option<u16>,
    pub endpoint: Option<String>,
    pub shared_secret: Option<String>,
    pub fingerprint: Option<String>,
    #[serde(default)]
    pub last_seen: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum InstanceStatus {
    Online,
    Offline,
    Unknown,
}

impl std::fmt::Display for InstanceStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            InstanceStatus::Online => write!(f, "online"),
            InstanceStatus::Offline => write!(f, "offline"),
            InstanceStatus::Unknown => write!(f, "unknown"),
        }
    }
}

/// Thread-safe manager for instance state.
pub struct InstanceManager {
    config: Mutex<ManagerConfig>,
    config_path: PathBuf,
}

impl InstanceManager {
    /// Create a new manager, loading config from the default path.
    ///
    /// On first launch, auto-generates a unique group token so each user
    /// gets an isolated peer namespace within the tunnelbroker group.
    pub fn new() -> Self {
        let config_path = Self::default_config_path();
        let mut config = Self::load_config(&config_path).unwrap_or_default();

        // Auto-generate a unique group token on first run
        if config.tunnelbroker_token.as_deref().unwrap_or("").is_empty() {
            let token = uuid::Uuid::new_v4().to_string();
            config.tunnelbroker_token = Some(token.clone());

            // Derive group name with Reddit-style auto-name
            // to prevent collisions across different users.
            config.tunnelbroker_group = crate::namegen::generate();

            // Persist immediately so the token survives restarts
            let _ = Self::save_config_inner(&config, &config_path);
        }

        Self {
            config: Mutex::new(config),
            config_path,
        }
    }

    /// Path to the config file (~/.config/kgtun-manager/config.json).
    fn default_config_path() -> PathBuf {
        let base = dirs::config_dir().unwrap_or_else(|| PathBuf::from("."));
        base.join("kgtun-manager").join("config.json")
    }

    fn load_config(path: &PathBuf) -> Option<ManagerConfig> {
        if !path.exists() {
            return None;
        }
        let data = std::fs::read_to_string(path).ok()?;
        serde_json::from_str(&data).ok()
    }

    fn save_config_inner(config: &ManagerConfig, path: &PathBuf) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let data = serde_json::to_string_pretty(config).map_err(|e| e.to_string())?;
        std::fs::write(path, data).map_err(|e| e.to_string())?;
        Ok(())
    }

    /// Persist the current config to disk.
    pub fn save_config(&self) -> Result<(), String> {
        let config = self.config.lock().map_err(|e| e.to_string())?;
        Self::save_config_inner(&config, &self.config_path)
    }

    /// Get a copy of the current config.
    pub fn get_config(&self) -> Result<ManagerConfig, String> {
        self.config.lock().map(|c| c.clone()).map_err(|e| e.to_string())
    }

    /// Update the config (replaces entirely).
    pub fn set_config(&self, config: ManagerConfig) -> Result<(), String> {
        let mut guard = self.config.lock().map_err(|e| e.to_string())?;
        *guard = config;
        Self::save_config_inner(&guard, &self.config_path)
    }

    /// Update tunnelbroker settings.
    pub fn set_tunnelbroker_config(
        &self,
        url: &str,
        group: &str,
        token: Option<String>,
    ) -> Result<(), String> {
        let mut guard = self.config.lock().map_err(|e| e.to_string())?;
        guard.tunnelbroker_url = url.to_string();
        guard.tunnelbroker_group = group.to_string();
        guard.tunnelbroker_token = token;
        Self::save_config_inner(&guard, &self.config_path)
    }

    /// Update or insert a cached instance state.
    pub fn upsert_instance(&self, state: InstanceState) -> Result<(), String> {
        let mut guard = self.config.lock().map_err(|e| e.to_string())?;
        guard.known_instances.insert(state.peer_id.clone(), state);
        Self::save_config_inner(&guard, &self.config_path)
    }

    /// Remove a known instance.
    pub fn remove_instance(&self, peer_id: &str) -> Result<(), String> {
        let mut guard = self.config.lock().map_err(|e| e.to_string())?;
        guard.known_instances.remove(peer_id);
        Self::save_config_inner(&guard, &self.config_path)
    }

    /// Merge tunnelbroker peer list into local state.
    pub fn sync_from_peers(&self, peers: &[crate::tunnelbroker::PeerInfo]) -> Result<Vec<InstanceState>, String> {
        let mut guard = self.config.lock().map_err(|e| e.to_string())?;
        let mut instances = Vec::new();

        for peer in peers {
            let endpoint = peer.endpoint.clone().or_else(|| {
                peer.contacts.first().map(|c| c.endpoint.clone())
            });

            let hostname = peer.metadata.get("hostname").and_then(|v| v.as_str()).map(String::from);
            let ssh_user = peer.metadata.get("ssh_user").and_then(|v| v.as_str()).map(String::from);
            let ssh_port = peer.metadata.get("ssh_port").and_then(|v| v.as_u64()).map(|p| p as u16);
            let fingerprint = peer.metadata.get("ssh_host_key_fingerprint")
                .and_then(|v| v.as_str()).map(String::from);

            let state = InstanceState {
                peer_id: peer.peer.clone(),
                label: peer.metadata.get("instance_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or(&peer.peer)
                    .to_string(),
                status: InstanceStatus::Online,
                hostname,
                ssh_user,
                ssh_port,
                endpoint,
                shared_secret: None, // secret not exposed via list_peers
                fingerprint,
                last_seen: Some(chrono::Utc::now().to_rfc3339()),
            };

            guard.known_instances.insert(peer.peer.clone(), state.clone());
            instances.push(state);
        }

        Self::save_config_inner(&guard, &self.config_path)?;
        Ok(instances)
    }
}
