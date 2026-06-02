<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import type { InstanceState } from './types';

  let { instance }: { instance: InstanceState } = $props();
  let expanded = $state(false);
  let cmdCopied = $state(false);
  let proxyStarting = $state(false);
  let proxyEnabled = $state(false);
  let proxyPort = $state(0);

  // Restore proxy state from backend on mount (survives refresh)
  onMount(async () => {
    try {
      const status: any = await invoke('get_instance_proxy_status', { peerId: instance.peer_id });
      if (status) {
        proxyEnabled = true;
        proxyPort = status.local_port;
      }
    } catch (_) { /* no proxy running */ }
  });

  function statusColor(s: string): string {
    return s === 'Online' ? '#22c55e' : s === 'Offline' ? '#ef4444' : '#6b7280';
  }
  function statusLabel(s: string): string {
    return s === 'Online' ? 'Connected' : s === 'Offline' ? 'Disconnected' : 'Unknown';
  }
  function timeAgo(iso: string | null): string {
    if (!iso) return 'never';
    const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    return m < 1 ? 'just now' : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ago`;
  }

  async function toggleProxy() {
    if (proxyEnabled) {
      proxyStarting = true;
      try {
        await invoke('stop_instance_proxy', { peerId: instance.peer_id });
        proxyEnabled = false;
        proxyPort = 0;
      } catch (e) { alert(`Failed to stop: ${e}`); }
      proxyStarting = false;
    } else {
      proxyStarting = true;
      try {
        const result: any = await invoke('start_instance_proxy', {
          peerId: instance.peer_id,
        });
        proxyPort = result.local_port;
        proxyEnabled = true;
      } catch (e) { alert(`Failed to start: ${e}`); }
      proxyStarting = false;
    }
  }

  async function sshConnect() {
    if (!proxyEnabled) { alert('Start proxy first'); return; }
    try {
      await invoke('ssh_connect_proxy', {
        peerId: instance.peer_id,
      });
    } catch (e) { alert(`SSH failed: ${e}`); }
  }

  async function copySshCmd() {
    if (!proxyEnabled) { alert('Start proxy first'); return; }
    try {
      const cmd: string = await invoke('build_ssh_command_with_password', {
        peerId: instance.peer_id,
      });
      await navigator.clipboard.writeText(cmd);
      cmdCopied = true;
      setTimeout(() => cmdCopied = false, 2000);
    } catch (e) { alert(`Copy failed: ${e}`); }
  }

  function toggleExpand() { expanded = !expanded; }
</script>

<tr class="instance-row">
  <td class="col-status">
    <span class="dot" style="background:{statusColor(instance.status)}"></span>
  </td>
  <td class="col-name">
    {instance.label}
    {#if proxyStarting}<span class="proxy-badge starting">starting\u2026</span>{/if}
    {#if proxyEnabled}<span class="proxy-badge active">:{proxyPort}</span>{/if}
  </td>
  <td class="col-host">{instance.hostname || '\u2014'}</td>
  <td class="col-url">
    <span class="url-text" title={instance.endpoint || ''}>
      {instance.endpoint ? instance.endpoint.replace(/^https?:\/\//, '').slice(0, 45) + '\u2026' : '\u2014'}
    </span>
  </td>
  <td class="col-uptime">{timeAgo(instance.last_seen)}</td>
  <td class="col-actions">
    <div class="action-btns">
      <button class="btn-icon" title="Open SSH terminal" onclick={sshConnect} disabled={!proxyEnabled || proxyStarting}>
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="16" height="16">
          <path stroke-linecap="round" stroke-linejoin="round" d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
      </button>
      <button class="btn-icon" title="Copy SSH command" onclick={copySshCmd} disabled={!proxyEnabled || proxyStarting}>
        {#if cmdCopied}
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/></svg>
        {:else}
          <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14"><path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z"/><path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z"/></svg>
        {/if}
      </button>
      <button class="btn-icon toggle" title={proxyEnabled ? 'Stop proxy' : 'Start proxy'} onclick={toggleProxy} disabled={proxyStarting}>
        {#if proxyStarting}
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="16" height="16" class="spin">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182"/>
          </svg>
        {:else if proxyEnabled}
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="16" height="16">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 9.563C9 9.252 9.252 9 9.563 9h4.874c.311 0 .563.252.563.563v4.874c0 .311-.252.563-.563.563H9.564A.562.562 0 0 1 9 14.437V9.564Z" />
          </svg>
        {:else}
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" width="16" height="16">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.91 11.672a.375.375 0 0 1 0 .656l-5.603 3.113a.375.375 0 0 1-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112Z" />
          </svg>
        {/if}
      </button>
      <button class="btn-icon" title="Show details" onclick={toggleExpand}>
        <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14" class:rotated={expanded}>
          <path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/>
        </svg>
      </button>
    </div>
  </td>
</tr>
{#if expanded}
  <tr class="detail-row">
    <td colspan="6">
      <div class="detail-panel">
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Peer ID</span>
            <code class="detail-value">{instance.peer_id}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">Tunnel URL</span>
            <code class="detail-value">{instance.endpoint || '\u2014'}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">Local Proxy</span>
            <code class="detail-value">{proxyEnabled ? `127.0.0.1:${proxyPort}` : 'Stopped'}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">SSH Port</span>
            <code class="detail-value">{instance.ssh_port ?? 2222}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">SSH User</span>
            <code class="detail-value">{instance.ssh_user ?? 'notebook'}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">Connected At</span>
            <code class="detail-value">{instance.last_seen ?? '\u2014'}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">Fingerprint</span>
            <code class="detail-value">{instance.fingerprint || '\u2014'}</code>
          </div>
          <div class="detail-item">
            <span class="detail-label">Status</span>
            <code class="detail-value" style="color:{statusColor(instance.status)}">{statusLabel(instance.status)}</code>
          </div>
        </div>
      </div>
    </td>
  </tr>
{/if}

<style>
  .instance-row { border-bottom: 1px solid var(--card-border); }
  .instance-row:hover { background: color-mix(in srgb, var(--card-bg) 96%, var(--text)); }
  .instance-row td { padding: 0.6rem 0.5rem; vertical-align: middle; }

  .col-status { width: 24px; text-align: center; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .col-name { font-weight: 600; white-space: nowrap; }
  .col-host { color: var(--muted); font-size: 0.8125rem; }
  .col-url { max-width: 200px; overflow: hidden; }
  .url-text { font-size: 0.75rem; color: var(--muted); font-family: monospace; white-space: nowrap; }
  .col-uptime { font-size: 0.75rem; color: var(--muted-light); white-space: nowrap; }

  .action-btns { display: flex; gap: 0.25rem; flex-wrap: nowrap; }
  .btn-icon {
    display: inline-flex; align-items: center; gap: 0.2rem;
    padding: 0.25rem 0.45rem; border-radius: 0.375rem; font-size: 0.6875rem;
    font-weight: 500; cursor: pointer; border: 1px solid var(--card-border);
    background: var(--card-bg); color: var(--text); white-space: nowrap;
    transition: background 0.1s;
  }
  .btn-icon:hover { background: var(--btn-ghost-hover); }
  .btn-icon.danger:hover { background: #fef2f2; color: #dc2626; border-color: #fecaca; }
  :global(.dark) .btn-icon.danger:hover { background: #3b1c1c; color: #fca5a5; border-color: #7f1d1d; }
  .btn-icon:disabled { opacity: 0.5; cursor: not-allowed; }

  .detail-row td { padding: 0; }
  .detail-panel {
    padding: 0.875rem 1.25rem;
    background: color-mix(in srgb, var(--card-bg) 97%, var(--text));
    border-top: 1px solid var(--card-border);
  }
  .detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 0.75rem; }
  .detail-item { display: flex; flex-direction: column; gap: 0.1rem; }
  .detail-label { font-size: 0.625rem; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .detail-value { font-size: 0.75rem; font-family: monospace; word-break: break-all; }

  .rotated { transform: rotate(180deg); }

  .proxy-badge {
    display: inline-block; font-size: 0.6rem; padding: 0.1rem 0.3rem;
    border-radius: 0.25rem; margin-left: 0.375rem; vertical-align: middle;
    font-weight: 600; font-family: monospace;
  }
  .proxy-badge.starting { background: #fef3c7; color: #92400e; }
  .proxy-badge.active { background: #d1fae5; color: #065f46; }
  :global(.dark) .proxy-badge.starting { background: #78350f; color: #fde68a; }
  :global(.dark) .proxy-badge.active { background: #064e3b; color: #a7f3d0; }

  .btn-icon.toggle:hover { background: var(--btn-ghost-hover); }
  .btn-icon:disabled { opacity: 0.4; cursor: not-allowed; }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spin { animation: spin 1s linear infinite; }
</style>
