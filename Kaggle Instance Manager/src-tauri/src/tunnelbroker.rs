//! Rust client for the tunnelbroker peer discovery API.
//!
//! Used by the Tauri backend to discover and manage Kaggle instances
//! registered in tunnelbroker.

use serde::{Deserialize, Serialize};

/// A peer record returned by the tunnelbroker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerInfo {
    pub peer: String,
    #[serde(default)]
    pub endpoint: Option<String>,
    #[serde(default)]
    pub contacts: Vec<Contact>,
    #[serde(default)]
    pub metadata: serde_json::Value,
    #[serde(default)]
    pub expires_at: Option<String>,
}

/// A single contact inside a peer record.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contact {
    pub endpoint: String,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(default)]
    pub priority: Option<i32>,
}

/// The tunnelbroker health endpoint response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub ok: bool,
    pub server: ServerInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerInfo {
    pub id: String,
    pub url: String,
    pub updated_at: String,
}

/// Client for making HTTP requests to tunnelbroker.
pub struct TunnelbrokerClient {
    base_url: String,
    group: String,
    group_token: Option<String>,
    client: reqwest::Client,
}

impl TunnelbrokerClient {
    pub fn new(base_url: &str, group: &str, group_token: Option<String>) -> Self {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        headers.insert(
            reqwest::header::USER_AGENT,
            "kaggle-tunnel/0.2.0".parse().unwrap(),
        );
        if let Some(ref token) = group_token {
            headers.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {}", token).parse().unwrap(),
            );
        }

        let client = reqwest::Client::builder()
            .default_headers(headers)
            .timeout(std::time::Duration::from_secs(15))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            base_url: base_url.trim_end_matches('/').to_string(),
            group: group.to_string(),
            group_token,
            client,
        }
    }

    /// Check server health.
    pub async fn health(&self) -> Result<HealthResponse, String> {
        let url = format!("{}/health", self.base_url);
        let resp = self.client.get(&url).send().await.map_err(|e| e.to_string())?;
        if !resp.status().is_success() {
            return Err(format!("Health check failed: {}", resp.status()));
        }
        resp.json().await.map_err(|e| e.to_string())
    }

    /// List all peers in the configured group.
    pub async fn list_peers(&self) -> Result<Vec<PeerInfo>, String> {
        let url = format!("{}/v1/groups/{}/peers", self.base_url, self.group);
        let resp = self.client.get(&url).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(format!("list_peers failed ({}): {}", status, body));
        }
        let data: serde_json::Value = resp.json().await.map_err(|e| e.to_string())?;
        let peers = data.get("peers")
            .and_then(|v| serde_json::from_value(v.clone()).ok())
            .unwrap_or_default();
        Ok(peers)
    }

    /// Get a single peer record.
    pub async fn get_peer(&self, peer_id: &str) -> Result<PeerInfo, String> {
        let url = format!("{}/v1/peers/{}?group={}", self.base_url, peer_id, self.group);
        let resp = self.client.get(&url).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(format!("get_peer failed ({}): {}", status, body));
        }
        resp.json().await.map_err(|e| e.to_string())
    }

    /// Create or update a peer record.
    pub async fn register_peer(
        &self,
        peer_id: &str,
        secret: &str,
        endpoint: Option<&str>,
        metadata: Option<serde_json::Value>,
    ) -> Result<serde_json::Value, String> {
        let url = format!("{}/v1/peers?group={}", self.base_url, self.group);
        let mut body = serde_json::json!({
            "peer": peer_id,
            "secret": secret,
        });
        if let Some(ep) = endpoint {
            body["endpoint"] = serde_json::json!(ep);
        }
        if let Some(md) = metadata {
            body["metadata"] = md;
        }
        let resp = self.client.post(&url).json(&body).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("register_peer failed ({}): {}", status, text));
        }
        resp.json().await.map_err(|e| e.to_string())
    }

    /// Delete a peer record. Requires the correct secret.
    pub async fn delete_peer(&self, peer_id: &str, secret: &str) -> Result<(), String> {
        let url = format!("{}/v1/peers/{}?group={}", self.base_url, peer_id, self.group);
        let body = serde_json::json!({ "secret": secret });
        let resp = self.client.delete(&url).json(&body).send().await.map_err(|e| e.to_string())?;
        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("delete_peer failed ({}): {}", status, text));
        }
        Ok(())
    }
}
