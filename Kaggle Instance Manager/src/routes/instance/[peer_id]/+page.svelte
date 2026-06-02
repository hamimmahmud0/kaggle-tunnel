<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import type { InstanceCredentials } from '$lib/types';
  import { statusError } from '$lib/stores';

  let creds = $state<InstanceCredentials | null>(null);
  let loading = $state(true);
  let showPassword = $state(false);
  let sshCmd = $state('');
  let cellCopied = $state(false);
  let localSecret = $state('');

  const peerId = $derived($page.params.peer_id);

  onMount(async () => {
    // Try to load secret from sessionStorage (set when cell was generated)
    localSecret = sessionStorage.getItem(`kgtun_secret_${peerId}`) || '';
    await loadCredentials();
  });

  async function loadCredentials() {
    loading = true;
    try {
      creds = await invoke('get_instance_credentials', { peerId });
      // Reversed-direction: SSH through local proxy on 127.0.0.1:10022
      sshCmd = `ssh -o StrictHostKeyChecking=accept-new -p 10022 notebook@127.0.0.1`;
    } catch (e) {
      statusError.set(`Failed to load credentials: ${e}`);
    } finally {
      loading = false;
    }
  }

  async function doSshConnect() {
    try {
      const result: string = await invoke('ssh_connect_proxy', { peerId });
      alert(result);
    } catch (e) {
      statusError.set(`SSH failed: ${e}`);
    }
  }

  async function copyCellCode() {
    try {
      const name = creds?.instance_name ?? peerId;
      const json: string = await invoke('generate_cell_code', { instanceName: name });
      const data = JSON.parse(json);
      await navigator.clipboard.writeText(data.cell);
      // Store secret for this instance
      sessionStorage.setItem(`kgtun_secret_${name}`, data.shared_secret);
      localSecret = data.shared_secret;
      cellCopied = true;
      setTimeout(() => cellCopied = false, 2000);
    } catch (e) {
      statusError.set(`Failed to generate cell: ${e}`);
    }
  }

  async function doDelete() {
    if (!confirm('Deregister this instance from tunnelbroker?')) return;
    try {
      await invoke('remove_instance', { peerId });
      window.location.href = '/';
    } catch (e) {
      statusError.set(`Delete failed: ${e}`);
    }
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      // Could add toast notification here
    });
  }
</script>

<div class="detail-page">
  <header class="detail-header">
    <a href="/" class="back-link">&larr; Back</a>
    <h1>{creds?.instance_name ?? peerId}</h1>
    <div class="header-actions">
      <button class="btn btn-danger" onclick={doDelete}>Deregister</button>
    </div>
  </header>

  {#if loading}
    <div class="loading">Loading credentials...</div>
  {:else if creds}
    <div class="detail-grid">
      <!-- SSH Connection -->
      <section class="card">
        <h2>SSH Connection</h2>
        <div class="field">
          <label>SSH Command</label>
          <div class="copy-row">
            <code class="mono-block">{sshCmd}</code>
            <button class="btn btn-sm" onclick={() => copyToClipboard(sshCmd)}>Copy</button>
          </div>
        </div>
        <div class="field">
          <label>Password / Shared Secret</label>
          <div class="copy-row">
            <code class="mono-block">
              {#if showPassword}
                {creds.shared_secret || localSecret || '(not available — generate a cell first)'}
              {:else}
                {'\u2022'.repeat(20)}
              {/if}
            </code>
            <button class="btn btn-sm" onclick={() => { showPassword = !showPassword; }}>
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>
        <button class="btn btn-primary ssh-btn" onclick={doSshConnect}>
          \U0001F4BB Connect SSH
        </button>
        <button class="btn btn-secondary ssh-btn" onclick={copyCellCode}>
          {#if cellCopied}
            <svg class="icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/>
            </svg>
            Copied!
          {:else}
            <svg class="icon" viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
              <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z"/>
              <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z"/>
            </svg>
            Copy Notebook Cell
          {/if}
        </button>
        <p class="ssh-hint">
          "Connect SSH" starts a local proxy and launches the terminal.
          "Copy Notebook Cell" generates the cell to paste into Kaggle.
        </p>
      </section>

      <!-- Instance Info -->
      <section class="card">
        <h2>Instance Info</h2>
        <div class="field">
          <label>Peer ID</label>
          <code class="mono-block">{creds.peer_id}</code>
        </div>
        <div class="field">
          <label>Hostname</label>
          <div class="copy-row">
            <code class="mono-block">{creds.hostname}</code>
            <button class="btn btn-sm" onclick={() => copyToClipboard(creds!.hostname)}>Copy</button>
          </div>
        </div>
        <div class="field">
          <label>SSH Port</label>
          <code class="mono-block">{creds.ssh_port}</code>
        </div>
        <div class="field">
          <label>SSH User</label>
          <code class="mono-block">{creds.ssh_user}</code>
        </div>
        {#if creds.fingerprint}
          <div class="field">
            <label>Host Key Fingerprint</label>
            <div class="copy-row">
              <code class="mono-block small">{creds.fingerprint}</code>
              <button class="btn btn-sm" onclick={() => copyToClipboard(creds!.fingerprint)}>Copy</button>
            </div>
          </div>
        {/if}
      </section>

      <!-- Tunnel Endpoint -->
      <section class="card">
        <h2>Tunnel / Endpoint</h2>
        <div class="field">
          <label>Tunnel URL</label>
          <div class="copy-row">
            <code class="mono-block">{creds.tunnel_endpoint}</code>
            <button class="btn btn-sm" onclick={() => copyToClipboard(creds!.tunnel_endpoint)}>Copy</button>
          </div>
        </div>
        <div class="field">
          <label>Endpoint (SSH target)</label>
          <div class="copy-row">
            <code class="mono-block">{creds.endpoint}</code>
            <button class="btn btn-sm" onclick={() => copyToClipboard(creds!.endpoint)}>Copy</button>
          </div>
        </div>
      </section>
    </div>
  {:else}
    <div class="error-state">Failed to load instance details.</div>
  {/if}
</div>

<style>
  .detail-page { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem; }

  .detail-header {
    display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem;
  }
  .detail-header h1 { flex: 1; font-size: 1.5rem; font-weight: 700; }
  .back-link { color: #3b82f6; text-decoration: none; font-size: 0.875rem; }
  .back-link:hover { text-decoration: underline; }

  .detail-grid { display: flex; flex-direction: column; gap: 1.5rem; }

  .card {
    background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 0.75rem;
    padding: 1.5rem;
  }
  .card h2 { font-size: 1rem; font-weight: 600; margin-bottom: 1rem; }

  .field { margin-bottom: 0.75rem; }
  .field label { display: block; font-size: 0.75rem; font-weight: 500; color: var(--muted); margin-bottom: 0.25rem; text-transform: uppercase; letter-spacing: 0.05em; }

  .copy-row { display: flex; gap: 0.5rem; align-items: center; }
  .mono-block {
    flex: 1; font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8125rem;
    background: var(--code-bg); padding: 0.375rem 0.5rem; border-radius: 0.25rem;
    word-break: break-all; line-height: 1.4;
  }
  .mono-block.small { font-size: 0.6875rem; }

  .ssh-btn { margin-top: 0.75rem; width: 100%; justify-content: center; padding: 0.75rem; }
  .icon { margin-right: 0.25rem; }
  .ssh-hint { margin-top: 0.5rem; font-size: 0.75rem; color: var(--muted-light); text-align: center; }

  .loading, .error-state { text-align: center; padding: 4rem; color: var(--muted); }

  .btn {
    display: inline-flex; align-items: center; gap: 0.375rem;
    padding: 0.5rem 1rem; border-radius: 0.5rem; font-size: 0.875rem;
    font-weight: 500; cursor: pointer; border: none; text-decoration: none;
    white-space: nowrap;
  }
  .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }
  .btn-primary { background: #3b82f6; color: white; }
  .btn-primary:hover { background: #2563eb; }
  .btn-danger { background: #ef4444; color: white; }
  .btn-danger:hover { background: #dc2626; }
</style>
