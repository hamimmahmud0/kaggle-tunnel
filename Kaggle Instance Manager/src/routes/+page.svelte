<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { onMount } from 'svelte';
  import InstanceCard from '$lib/InstanceCard.svelte';
  import type { InstanceState, ManagerConfig } from '$lib/types';
  import { instances, config, refreshing, statusMessage, statusError, lastRefreshed } from '$lib/stores';

  let configured = $state(false);

  onMount(async () => {
    await loadConfig();
  });

  async function loadConfig() {
    try {
      const cfg: ManagerConfig = await invoke('get_config');
      config.set(cfg);
      configured = !!cfg.tunnelbroker_url;
      if (configured) {
        await doRefresh();
      }
    } catch (e) {
      statusError.set(`Failed to load config: ${e}`);
    }
  }

  async function doRefresh() {
    refreshing.set(true);
    statusMessage.set('Refreshing instances from tunnelbroker...');
    statusError.set(null);
    try {
      const result: InstanceState[] = await invoke('refresh_instances');
      instances.set(result);
      lastRefreshed.set(new Date().toISOString());
      statusMessage.set(`Found ${result.length} instance(s)`);
      setTimeout(() => statusMessage.set(null), 3000);
    } catch (e) {
      statusError.set(`Refresh failed: ${e}`);
    } finally {
      refreshing.set(false);
    }
  }
</script>

<div class="app-shell">
  <header class="header">
    <div class="header-inner">
      <div class="header-left">
        <h1 class="app-title">Kaggle Instance Manager</h1>
        {#if $lastRefreshed}
          <span class="last-refresh">updated {$lastRefreshed}</span>
        {/if}
      </div>
      <nav class="header-nav">
        <a href="/settings" class="btn btn-ghost">Settings</a>
        <button class="btn btn-primary" onclick={doRefresh} disabled={$refreshing}>
          {$refreshing ? 'Refreshing...' : '⟳ Refresh'}
        </button>
      </nav>
    </div>
  </header>

  {#if $statusMessage}
    <div class="status-bar info">{$statusMessage}</div>
  {/if}
  {#if $statusError}
    <div class="status-bar error">{$statusError}</div>
  {/if}

  <main class="main">
    {#if !configured}
      <div class="empty-state">
        <div class="empty-icon">📡</div>
        <h2>No tunnelbroker configured</h2>
        <p>Configure your tunnelbroker connection in Settings to discover running instances.</p>
        <a href="/settings" class="btn btn-primary">Go to Settings</a>
      </div>
    {:else if $instances.length === 0 && !$refreshing}
      <div class="empty-state">
        <div class="empty-icon">🔌</div>
        <h2>No instances found</h2>
        <p>
          No peers registered in tunnelbroker group "<strong>{$config.tunnelbroker_group}</strong>".
          Make sure your notebook cells are running and registered.
        </p>
        <button class="btn btn-primary" onclick={doRefresh}>Refresh</button>
      </div>
    {:else}
      <div class="table-wrap">
        <table class="instance-table">
          <thead>
            <tr>
              <th class="th-status"></th>
              <th class="th-name">Name</th>
              <th class="th-host">Host</th>
              <th class="th-url">Tunnel URL</th>
              <th class="th-uptime">Seen</th>
              <th class="th-actions">Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each $instances as inst (inst.peer_id)}
              <InstanceCard instance={inst} />
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </main>
</div>

<style>
  .app-shell { display: flex; flex-direction: column; min-height: 100vh; }

  .header {
    background: var(--header-bg); border-bottom: 1px solid var(--header-border); padding: 1rem 1.5rem;
    position: sticky; top: 0; z-index: 10;
  }
  .header-inner { max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; }
  .header-left { display: flex; align-items: baseline; gap: 0.75rem; }
  .app-title { font-size: 1.25rem; font-weight: 700; }
  .last-refresh { font-size: 0.75rem; color: var(--muted-light); }
  .header-nav { display: flex; gap: 0.5rem; align-items: center; }

  .status-bar { padding: 0.5rem 1.5rem; font-size: 0.875rem; text-align: center; }
  .status-bar.info { background: var(--status-info-bg); color: var(--status-info-text); }
  .status-bar.error { background: var(--status-error-bg); color: var(--status-error-text); }

  .main { flex: 1; max-width: 1200px; width: 100%; margin: 0 auto; padding: 2rem 1.5rem; }
  .table-wrap { overflow-x: auto; }
  .instance-table { width: 100%; border-collapse: collapse; }
  .instance-table thead th {
    padding: 0.5rem; font-size: 0.6875rem; font-weight: 600;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em;
    text-align: left; border-bottom: 2px solid var(--card-border);
  }
  .th-status { width: 24px; }
  .th-actions { text-align: right; }

  .empty-state {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    text-align: center; padding: 4rem 2rem; gap: 0.75rem;
  }
  .empty-icon { font-size: 3rem; margin-bottom: 0.5rem; }
  .empty-state h2 { font-size: 1.25rem; font-weight: 600; }
  .empty-state p { color: var(--empty-text); max-width: 400px; line-height: 1.5; }

  .btn {
    display: inline-flex; align-items: center; gap: 0.375rem;
    padding: 0.5rem 1rem; border-radius: 0.5rem; font-size: 0.875rem;
    font-weight: 500; cursor: pointer; border: none; text-decoration: none;
  }
  .btn:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-primary { background: #3b82f6; color: white; }
  .btn-primary:hover:not(:disabled) { background: #2563eb; }
  .btn-ghost { background: var(--btn-ghost-bg); color: var(--muted); }
  .btn-ghost:hover { background: var(--btn-ghost-hover); }
</style>