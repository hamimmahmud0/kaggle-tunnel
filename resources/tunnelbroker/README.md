# Tunnelbroker

Cloudflare Worker peer discovery service for HTTP tunnel contacts.

## Features

- multi-tenant peer registry
- peer-owned contact updates with per-peer secrets
- 12 hour default peer TTL
- optional group bearer tokens
- signed server-to-server replication
- public server discovery
- protected server cleanup for stale records
- Obsidian-compatible API docs

## Deploy

1. Install dependencies:

   ```sh
   npm install
   ```

2. Configure `wrangler.toml`:

   - `id`: production KV namespace id for this Cloudflare account
   - `preview_id`: optional preview KV namespace id
   - `PUBLIC_URL`: deployed Worker URL
   - `SERVER_ID`: stable id for this server, such as `main` or `secondary`
   - `GROUP_KEYS`: optional JSON object of group bearer tokens
   - `PEER_TTL_SECONDS`: defaults to `43200`, which is 12 hours
   - `SERVER_TTL_SECONDS`: defaults to `43200`

3. Set the cluster secret:

   ```sh
   npx wrangler secret put CLUSTER_SECRET
   ```

4. Deploy:

   ```sh
   npm run deploy
   ```

## Multiple Servers

Use a unique `PUBLIC_URL` and `SERVER_ID` per deployment.

Example primary:

```toml
PUBLIC_URL = "https://tunnelbroker.hamimmahmud0.workers.dev"
SERVER_ID = "main"
```

Example secondary:

```toml
PUBLIC_URL = "https://tunnelbroker.sam2yolo.workers.dev"
SERVER_ID = "secondary"
```

After deploying a new server, join it to an existing server with the signed `POST /v1/servers/join` endpoint.

## Docs

Start with [docs/API.md](docs/API.md). The docs are split into Obsidian-compatible notes with wiki links.
