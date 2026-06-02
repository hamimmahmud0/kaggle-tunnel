import { writable } from 'svelte/store';
import type { InstanceState, ManagerConfig } from './types';

// Current list of instances (from tunnelbroker sync)
export const instances = writable<InstanceState[]>([]);

// Currently loaded config
export const config = writable<ManagerConfig>({
  tunnelbroker_url: 'https://tunnelbroker.hamimmahmud0.workers.dev',
  tunnelbroker_group: 'default',
  tunnelbroker_token: null,
  cloudflared_path: null,
  known_instances: {},
});

// Whether a refresh is in progress
export const refreshing = writable(false);

// Error / status messages
export const statusMessage = writable<string | null>(null);
export const statusError = writable<string | null>(null);

// Last refresh timestamp
export const lastRefreshed = writable<string | null>(null);
