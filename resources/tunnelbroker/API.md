# Peer Registry API

This is the Obsidian entry note for the API documentation.

## Pages

- [[API Overview]]
- [[Authentication]]
- [[Peer Endpoints]]
- [[Server Endpoints]]
- [[Examples]]

## Quick Facts

- Base URL: `https://tunnelbroker.hamimmahmud0.workers.dev`
- Peer endpoint prefix: `/v1`
- Default peer TTL: `43200` seconds, or 12 hours
- Peer records are isolated by `group`
- Peer writes are protected by a per-peer `secret`
- Optional group tokens use `Authorization: Bearer <token>`
- Server replication uses HMAC signatures with `CLUSTER_SECRET`

## Endpoint Index

| Method | Path | Page |
| --- | --- | --- |
| `GET` | `/health` | [[API Overview#Health]] |
| `POST` | `/v1/peers?group=<group>` | [[Peer Endpoints#Create Or Update Peer]] |
| `GET` | `/v1/peers/<peer>?group=<group>` | [[Peer Endpoints#Get Peer]] |
| `DELETE` | `/v1/peers/<peer>?group=<group>` | [[Peer Endpoints#Delete Peer]] |
| `GET` | `/v1/groups/<group>/peers` | [[Peer Endpoints#List Group Peers]] |
| `GET` | `/v1/servers` | [[Server Endpoints#List Servers]] |
| `GET` | `/v1/discovery/servers` | [[Server Endpoints#Public Server Discovery]] |
| `POST` | `/v1/servers/register` | [[Server Endpoints#Register Server]] |
| `POST` | `/v1/servers/join` | [[Server Endpoints#Join Server]] |
| `POST` | `/v1/servers/cleanup` | [[Server Endpoints#Cleanup Servers]] |
| `POST` | `/v1/replicate` | [[Server Endpoints#Replicate]] |
