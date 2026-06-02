# Server Endpoints

Back to [[API]].

Server admin endpoints require [[Authentication#Cluster Authentication]].

## List Servers

### `GET /v1/servers`

Protected list of known registry servers.

## Public Server Discovery

### `GET /v1/discovery/servers`

Public read-only list of known registry servers.

## Register Server

### `POST /v1/servers/register`

```json
{
  "id": "secondary",
  "url": "https://tunnelbroker-secondary.example.workers.dev"
}
```

## Join Server

### `POST /v1/servers/join`

```json
{
  "bootstrapUrl": "https://tunnelbroker-main.example.workers.dev",
  "id": "secondary",
  "url": "https://tunnelbroker-secondary.example.workers.dev"
}
```

## Cleanup Servers

### `POST /v1/servers/cleanup`

Remove stale server records by id, URL, or expired `expiresAt`.

```json
{
  "ids": ["old-server-id"],
  "urls": ["https://old-worker.example.workers.dev"],
  "expired": true
}
```

## Replicate

### `POST /v1/replicate`

Internal endpoint used by servers to copy peer and server changes.
