# API Overview

Back to [[API]].

## Base URL

```txt
https://tunnelbroker.hamimmahmud0.workers.dev
```

All peer endpoints are under `/v1`.

## Storage Model

Peer records:

```txt
peer:<group>:<peer>
```

Server records:

```txt
server:<server-id>
```

## TTL

Peer records default to `43200` seconds, which is 12 hours.

Server records default to `43200` seconds. Active servers refresh their own server record when they receive requests. Inactive servers are hidden from discovery after `expiresAt` and are also removed by KV TTL.

## Health

### `GET /health`

Returns the current server identity.

```json
{
  "ok": true,
  "server": {
    "id": "main",
    "url": "https://tunnelbroker.hamimmahmud0.workers.dev",
    "updatedAt": "2026-05-18T13:00:00.000Z"
  }
}
```
