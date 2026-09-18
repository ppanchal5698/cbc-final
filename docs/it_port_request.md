# IT request: publish CBC Estimating Copilot ports

Copy everything below the line into a ticket.

---

**Subject:** Inbound firewall / NAT — CBC Estimating Copilot (Windows Docker host DLP29)

**Application:** CBC Estimating Copilot (Ops-Hub)

**Runtime:** Docker Compose on a Windows host (`infra/docker-compose.yml`, Docker Desktop).

**Request:** Allow inbound **TCP** from **any source (`0.0.0.0/0`)** to this host on the ports below, and allow the same ports on the Windows host firewall. NAT/port-forward the public WAN IP to the LAN address below. Also allow the listed **outbound** destinations so the app can call vendors and model APIs.

### Host details

| Field | Value |
| --- | --- |
| Host name | `DLP29` |
| DNS suffix | `digzplacements.com` |
| Active adapter | Wi-Fi (Ethernet is disconnected) |
| Internal LAN IPv4 | `192.168.6.67` |
| Subnet mask | `255.255.252.0` |
| Default gateway | `192.168.5.1` |
| Host public IP / NAT target | **IT to confirm WAN/public IP** and forward to `192.168.6.67` (not visible from `ipconfig`) |
| Internal UI URL | `http://192.168.6.67:3000` |
| Internal API URL | `http://192.168.6.67:8001` |
| Public UI URL | `http://<PUBLIC_IP>:3000` |
| Public API URL | `http://<PUBLIC_IP>:8001` |

Hyper-V/WSL virtual switches (`172.30.0.1`, `172.29.192.1`) are host-local only. Do **not** NAT to those.

### Inbound TCP

Destination: `192.168.6.67` (`DLP29`), then the matching public IP after NAT.

| Port | Protocol | Service | Container | Why |
| --- | --- | --- | --- | --- |
| **3000** | TCP / HTTP | Web UI (Next.js Ops-Hub) | `cbc-final-web` | User-facing application |
| **8001** | TCP / HTTP | Platform API (FastAPI) | `cbc-final-platform` | API clients and health checks (`GET /api/health`) |
| **27017** | TCP | MongoDB | `cbc-final-mongo` | Datastore and job queue. **Require a unique strong password; do not leave the default `cbc` / `cbc_local_dev`.** |
| **3310** | TCP | ClamAV clamd | `cbc-final-clamav` | Malware scan of file uploads |
| **8000** | TCP / HTTP | MinerU PDF parser | `cbc-final-mineru` | GPU parse API. Needed when the GPU profile is enabled. |
| **4000** | TCP / HTTP | LiteLLM gateway | `cbc-final-litellm` | LLM proxy. Needed when the `oss` profile is enabled. |

**No inbound port needed:** background `worker` and `parser` poll MongoDB; MCP servers use stdio (no TCP listen).

There is no Redis, MinIO, or nginx in this stack.

### Security note

Publishing MongoDB (`27017`) and ClamAV (`3310`) to `0.0.0.0/0` is high risk. Prefer IP allowlisting over the whole internet if policy allows. Rotate Mongo and application secrets **before** these ports are reachable. TLS or a reverse proxy is strongly recommended for HTTP services (3000, 8001, 8000, 4000).

### Outbound (usually already allowed)

| Destination | Port | Purpose |
| --- | --- | --- |
| `api.anthropic.com` and related Anthropic endpoints | TCP 443 | Claude CLI / extraction |
| Docker Hub / GHCR | TCP 443 | Image pulls |
| Hugging Face | TCP 443 | MinerU model weights (GPU profile) |
| Optional: OpenRouter, NVIDIA NIM, customer P21 ERP, S3 | TCP 443 | Pricing, catalog, object storage |
| Host Ollama if used | TCP 11434 | Local LLM via `host.docker.internal` |

DNS (UDP/TCP 53) must work.

### Verification after the change

From another machine on the LAN (`192.168.4.0/22`):

```text
curl http://192.168.6.67:3000/signin
curl http://192.168.6.67:8001/api/health
```

From the internet, after NAT is in place (replace with the WAN IP IT assigns):

```text
curl http://<PUBLIC_IP>:3000/signin
curl http://<PUBLIC_IP>:8001/api/health
```

MongoDB, ClamAV, and MinerU should only be probed from an approved test host.

---

## App-side settings (after IT opens the ports)

Set these in the repo-root `.env` so a remote browser can sign in. Add the public URL once IT confirms the WAN IP.

```dotenv
API_BIND=0.0.0.0
CORS_ORIGINS=http://localhost:3000,http://192.168.6.67:3000,http://<PUBLIC_IP>:3000
NEXTAUTH_URL=http://192.168.6.67:3000
```

Rotate before publishing:

- `MONGO_ROOT_PASSWORD` (and matching `MONGODB_URI`)
- `APP_SECRET_KEY`
- `INTERNAL_API_TOKEN`
- `INTERNAL_JWT_SECRET`
- `AUTH_SECRET`

Then recreate the stack:

```bash
docker compose -f infra/docker-compose.yml up -d
```

GPU parser (also publishes MinerU `:8000`):

```bash
docker compose -f infra/docker-compose.yml --env-file .env --env-file infra/mineru/low.env --profile gpu up -d
```
