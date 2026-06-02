<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import type { ManagerConfig } from '$lib/types';
  import { config, statusError, statusMessage } from '$lib/stores';

  let url = $state('');
  let group = $state('default');
  let token = $state('');
  let saving = $state(false);
  let cellCopied = $state(false);
  let cellLoading = $state(false);

  onMount(async () => {
    await loadConfig();
  });

  async function loadConfig() {
    try {
      const cfg: ManagerConfig = await invoke('get_config');
      url = cfg.tunnelbroker_url;
      group = cfg.tunnelbroker_group;
      token = cfg.tunnelbroker_token ?? '';
    } catch (e) {
      statusError.set(`Failed to load config: ${e}`);
    }
  }

  async function saveConfig() {
    saving = true;
    statusError.set(null);
    statusMessage.set('Saving configuration...');
    try {
      await invoke('set_tunnelbroker_config', {
        url: url.trim(),
        group: group.trim(),
        token: token.trim() || null,
      });
      // Reload config into store
      const cfg: ManagerConfig = await invoke('get_config');
      config.set(cfg);
      statusMessage.set('Configuration saved successfully!');
      setTimeout(() => statusMessage.set(null), 3000);
    } catch (e) {
      statusError.set(`Failed to save: ${e}`);
    } finally {
      saving = false;
    }
  }

  async function copyCellCode() {
    cellLoading = true;
    try {
      // Generate a random Reddit-style name for this instance
      const instanceName: string = await invoke('generate_instance_name');
      const json: string = await invoke('generate_cell_code', { instanceName });
      const data = JSON.parse(json);
      await navigator.clipboard.writeText(data.cell);
      statusMessage.set(`Cell generated for "${instanceName}" — password derived from group token`);
      setTimeout(() => statusMessage.set(null), 3000);
      cellCopied = true;
      setTimeout(() => cellCopied = false, 2000);
    } catch (e) {
      statusError.set(`Failed to generate cell: ${e}`);
    } finally {
      cellLoading = false;
    }
  }

  async function testConnection() {
    statusError.set(null);
    statusMessage.set('Testing tunnelbroker connection...');
    try {
      // Try a simple health check via refresh_instances
      await invoke('refresh_instances');
      statusMessage.set('Connection successful!');
      setTimeout(() => statusMessage.set(null), 3000);
    } catch (e) {
      statusError.set(`Connection failed: ${e}`);
    }
  }
</script>

<div class="settings-page">
  <header class="settings-header">
    <a href="/" class="back-link">&larr; Back</a>
    <h1>Settings</h1>
  </header>

  {#if $statusMessage}
    <div class="status-bar info">{$statusMessage}</div>
  {/if}
  {#if $statusError}
    <div class="status-bar error">{$statusError}</div>
  {/if}

  <div class="settings-form">
    <section class="card">
      <h2>Tunnelbroker Connection</h2>
      <p class="desc">
        Configure the tunnelbroker Worker URL and group to discover your running Kaggle instances.
      </p>

      <div class="field">
        <label for="url">Tunnelbroker URL</label>
        <input
          id="url"
          type="url"
          bind:value={url}
          placeholder="https://tunnelbroker.hamimmahmud0.workers.dev"
          class="input"
        />
      </div>

      <div class="field">
        <label for="group">Group Name</label>
        <input
          id="group"
          type="text"
          bind:value={group}
          placeholder="default"
          class="input"
        />
        <span class="hint">Peers in this group will be visible as instances.</span>
      </div>

      <div class="field">
        <label for="token">Group Token</label>
        <div class="field-row">
          <input
            id="token"
            type="text"
            bind:value={token}
            placeholder="Auto-generated unique token"
            class="input mono"
          />
          <button class="btn btn-sm btn-secondary" onclick={async () => {
            try {
              const json: string = await invoke('regenerate_token');
              const data = JSON.parse(json);
              token = data.token;
              group = data.group;
              statusMessage.set(`Token regenerated — group: ${data.group}`);
              setTimeout(() => statusMessage.set(null), 2000);
            } catch (e) {
              statusError.set(`Failed to regenerate token: ${e}`);
            }
          }}>Regenerate</button>
        </div>
        <span class="hint">
          Auto-generated UUID unique to this manager instance. The notebook cell
          must pass the same token so the instance can register under your group.
          The SSH password is derived from this token (first 10 alphabetic characters),
          so both sides know it automatically. Click <strong>Regenerate</strong> to create
          a new token + group name, then <strong>Save</strong>.
        </span>
      </div>

      <div class="btn-row">
        <button class="btn btn-primary" onclick={saveConfig} disabled={saving}>
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button class="btn btn-secondary" onclick={testConnection}>
          Test Connection
        </button>
      </div>
    </section>

    <section class="card">
      <h2>Notebook Cell Generator</h2>
      <p class="desc">
        Generate a notebook cell that, when run on Kaggle, will start an SSH
        server, create a tunnel, and register this instance in tunnelbroker.
        The code is copied to your clipboard — paste it into a Kaggle notebook cell.
      </p>
      <button class="btn btn-primary copy-btn" onclick={copyCellCode} disabled={cellLoading}>
        {#if cellLoading}
          Generating…
        {:else if cellCopied}
          <svg class="icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
            <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clip-rule="evenodd"/>
          </svg>
          Copied!
        {:else}
          <svg class="icon" viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
            <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z"/>
            <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-5.879a1.5 1.5 0 00-.44-1.06L9.44 6.439A1.5 1.5 0 008.378 6H4.5z"/>
          </svg>
          Copy Notebook Cell
        {/if}
      </button>
    </section>
  </div>
</div>

<style>
  .settings-page { max-width: 600px; margin: 0 auto; padding: 2rem 1.5rem; }

  .settings-header {
    display: flex; align-items: center; gap: 1rem; margin-bottom: 2rem;
  }
  .settings-header h1 { font-size: 1.5rem; font-weight: 700; }
  .back-link { color: #3b82f6; text-decoration: none; font-size: 0.875rem; }
  .back-link:hover { text-decoration: underline; }

  .settings-form { display: flex; flex-direction: column; gap: 1.5rem; }

  .status-bar { padding: 0.5rem 1.5rem; font-size: 0.875rem; text-align: center; border-radius: 0.5rem; margin-bottom: 1rem; }
  .status-bar.info { background: var(--status-info-bg); color: var(--status-info-text); }
  .status-bar.error { background: var(--status-error-bg); color: var(--status-error-text); }

  .card {
    background: var(--card-bg); border: 1px solid var(--card-border); border-radius: 0.75rem;
    padding: 1.5rem;
  }
  .card h2 { font-size: 1rem; font-weight: 600; margin-bottom: 0.5rem; }
  .desc { font-size: 0.8125rem; color: var(--muted); margin-bottom: 1.25rem; line-height: 1.5; }

  .field { margin-bottom: 1rem; }
  .field label { display: block; font-size: 0.8125rem; font-weight: 500; margin-bottom: 0.375rem; }
  .field-row { display: flex; gap: 0.5rem; align-items: stretch; }
  .field-row .input { flex: 1; }
  .input {
    width: 100%; padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1;
    border-radius: 0.375rem; font-size: 0.875rem; background: var(--input-bg); color: var(--text);
  }
  :global(.dark) .input { border-color: #475569; }
  .input.mono { font-family: 'SF Mono', 'Fira Code', monospace; font-size: 0.8125rem; letter-spacing: 0.02em; }
  .hint { display: block; font-size: 0.75rem; color: #94a3b8; margin-top: 0.25rem; }

  .btn-row { display: flex; gap: 0.5rem; margin-top: 0.5rem; }



  .copy-btn { justify-content: center; width: 100%; padding: 0.75rem; }
  .copy-btn .icon { margin-right: 0.375rem; }

  .btn {
    display: inline-flex; align-items: center; gap: 0.375rem;
    padding: 0.5rem 1rem; border-radius: 0.5rem; font-size: 0.875rem;
    font-weight: 500; cursor: pointer; border: none; text-decoration: none;
  }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }
  .btn-primary { background: #3b82f6; color: white; }
  .btn-primary:hover:not(:disabled) { background: #2563eb; }
  .btn-secondary { background: var(--btn-secondary-bg); color: var(--btn-secondary-text); }
  .btn-secondary:hover { background: #cbd5e1; }
  :global(.dark) .btn-secondary { background: var(--btn-secondary-bg); color: var(--btn-secondary-text); }
  :global(.dark) .btn-secondary:hover { background: #475569; }
</style>
