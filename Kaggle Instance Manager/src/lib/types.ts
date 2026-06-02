// Shared types for the Kaggle Instance Manager

export interface InstanceState {
  peer_id: string;
  label: string;
  status: 'Online' | 'Offline' | 'Unknown';
  hostname: string | null;
  ssh_user: string | null;
  ssh_port: number | null;
  endpoint: string | null;
  shared_secret: string | null;
  fingerprint: string | null;
  last_seen: string | null;
}

export interface InstanceCredentials {
  peer_id: string;
  instance_name: string;
  hostname: string;
  ssh_user: string;
  ssh_port: number;
  endpoint: string;
  fingerprint: string;
  shared_secret: string;
  tunnel_endpoint: string;
}

export interface ManagerConfig {
  tunnelbroker_url: string;
  tunnelbroker_group: string;
  tunnelbroker_token: string | null;
  cloudflared_path: string | null;
  known_instances: Record<string, InstanceState>;
}
