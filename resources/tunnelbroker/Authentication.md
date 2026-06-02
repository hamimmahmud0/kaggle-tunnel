# Authentication

Back to [[API]].

## Peer Ownership

Peer ownership is verified with a per-peer `secret` in write and delete request bodies.

The first successful registration stores a SHA-256 hash of that secret. Future updates or deletes for the same `group` and `peer` must use the same secret.

## Group Tokens

Optional group authorization is configured with `GROUP_KEYS` in `wrangler.toml`:

```json
{"teamA":"team-a-token"}
```

When a group token exists, peer read/write/list requests must include:

```http
Authorization: Bearer team-a-token
```

## Cluster Authentication

Server-to-server endpoints require HMAC headers generated with `CLUSTER_SECRET`.

```http
X-Cluster-Timestamp: <unix-seconds>
X-Cluster-Signature: <hmac-sha256(timestamp + "\n" + raw-body)>
```

The timestamp must be within 5 minutes of the receiving server's current time.
