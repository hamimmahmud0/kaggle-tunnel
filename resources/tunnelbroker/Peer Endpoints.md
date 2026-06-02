# Peer Endpoints

Back to [[API]].

## Create Or Update Peer

### `POST /v1/peers?group=<group>`

```json
{
  "peer": "peer-a",
  "secret": "peer-owned-secret",
  "endpoint": "https://abc.trycloudflare.com",
  "metadata": {
    "hostname": "laptop-a"
  }
}
```

Multiple contacts:

```json
{
  "peer": "peer-a",
  "secret": "peer-owned-secret",
  "contacts": [
    {
      "endpoint": "https://abc.trycloudflare.com",
      "label": "primary",
      "priority": 10
    }
  ]
}
```

## Get Peer

### `GET /v1/peers/<peer>?group=<group>`

Returns one peer's public contacts.

## Delete Peer

### `DELETE /v1/peers/<peer>?group=<group>`

```json
{
  "secret": "peer-owned-secret"
}
```

## List Group Peers

### `GET /v1/groups/<group>/peers`

Lists all currently live peers in a group.
