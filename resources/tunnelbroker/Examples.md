# Examples

Back to [[API]].

## Register A Peer

```sh
curl -X POST 'https://tunnelbroker.example.workers.dev/v1/peers?group=teamA' \
  -H 'content-type: application/json' \
  -d '{
    "peer": "peer-a",
    "secret": "peer-owned-secret",
    "endpoint": "https://abc.trycloudflare.com"
  }'
```

## Fetch A Peer

```sh
curl 'https://tunnelbroker.example.workers.dev/v1/peers/peer-a?group=teamA'
```

## Discover Servers

```sh
curl 'https://tunnelbroker.example.workers.dev/v1/discovery/servers'
```

## Signed Cleanup

```sh
body='{"ids":["old-id"],"expired":true}'
secret=$(rg -o '[a-f0-9]{64}' secrets.txt | head -n1)
ts=$(date +%s)
sig=$(printf '%s\n%s' "$ts" "$body" | openssl dgst -sha256 -hmac "$secret" -binary | xxd -p -c 256)

curl -X POST 'https://tunnelbroker.example.workers.dev/v1/servers/cleanup' \
  -H 'content-type: application/json' \
  -H "x-cluster-timestamp: $ts" \
  -H "x-cluster-signature: $sig" \
  --data "$body"
```
