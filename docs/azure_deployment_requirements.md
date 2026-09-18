# Azure Deployment Requirements: 100% Self-Contained Container Stack

## CBC Estimating Copilot (Ops-Hub)

**Customer:** The Hamilton Parker Company — Construction Building Components (CBC)
**Partner / Delivery:** Dash Technologies Inc.
**Architecture Model:** **Pure Container Architecture (Zero External Managed Services)**
**Target Environment:** Azure Linux Virtual Machine (Compute + Managed Disk Only)
**Date:** September 17, 2026
**Document Version:** 3.0
**Source Repository:** `cbc-final` (`infra/docker-compose.yml`, `apps/web`, `apps/backend`)

---

## 1. Executive Summary & Core Principle

This specification defines the deployment requirements for running the **CBC Estimating Copilot exclusively using Docker containers**, with **zero dependency on external managed cloud PaaS services**.

### Core Tenets of the 100% Containerized Architecture

* **NO Azure Cosmos DB or Managed Databases:** MongoDB 7 runs as a containerized replica set (`rs0`) with internal keyfile authentication and multi-document ACID transactions (`infra/docker/mongo-keyfile-entrypoint.sh`).
* **NO Azure Files NFS or Azure Blob Storage PaaS:** Project bid PDFs, vendor pricebooks, and extraction artifacts are stored on high-speed **Azure Managed Disks (Premium SSD)** mounted directly into the containers.
* **NO Azure Key Vault:** All credentials, JWT secrets, and API keys are stored in a secured host-level `.env` file (permissions `600`), injected directly into containers at runtime.
* **NO Azure Application Gateway or Azure Front Door:** Ingress, TLS 1.3 termination, and path routing are handled by a lightweight **containerized reverse proxy** (Caddy with automatic Let's Encrypt SSL or Nginx).
* **NO Azure Service Bus or Cloud Queues:** Asynchronous pipeline jobs are queued, claimed, and heartbeated directly inside the containerized MongoDB `jobs` collection.

---

## 2. Complete Container Topology & Service Map

The entire application runs as a unified multi-container system via Docker Compose:

```mermaid
flowchart TB
    subgraph Internet["Public Ingress (HTTPS)"]
        Users["Estimators (Kevin, Rick, Shanna)\n& Sales Initiators (Kellan, Matt, Tina)"]
    end

    subgraph Azure_VM["Azure Linux VM (Standard_D8s_v5 or GPU Standard_NC4as_T4_v3)"]
        subgraph Ingress_Layer["Containerized Ingress"]
            Caddy["edge-proxy (Caddy / Nginx Container)\n- Ports 80 & 443 Exposed to Public\n- Automatic Let's Encrypt TLS 1.3\n- Path Routing:\n  * /api/* -> platform:8001\n  * /* -> web:3000"]
        end

        subgraph Application_Containers["Application Containers (Internal Bridge Network: cbc-final)"]
            Web["web: cbc-final-web (Next.js 14)\nPort 3000 (Internal)\nProxies to http://platform:8001"]
            API["platform: cbc-final-platform (FastAPI)\nPort 8001 (Internal)\n7 Modular Monolith Domains\nStartup Migrations + Read-Only User Setup"]
            Worker["worker: cbc-final-worker\npython -m cbc.app.worker\nWORKER_CLAIM_ALL=1\nClaude CLI + MCP Servers (stdio)"]
            ClamAV["clamav: cbc-final-clamav\nclamav/clamav:stable\nPort 3310 (Internal)"]
        end

        subgraph Database_Containers["Database Containers (Internal Network)"]
            Mongo["mongo: cbc-final-mongo (mongo:7)\n- Single-Node Replica Set rs0\n- Keyfile Auth (/mongo-keyfile)\n- Port 27017 (Internal Only)"]
            MongoInit["mongo-init: cbc-final-mongo-init\n- Runs mongo-rs-init.sh on boot\n- Idempotent rs0 initiator"]
        end

        subgraph Optional_GPU["Optional GPU Profile Containers (--profile gpu)"]
            MinerU["mineru: cbc-final-mineru\nNVIDIA CUDA / Port 8000\nLayout & Table Parser"]
            Parser["parser: cbc-final-parser\nWORKER_DOMAIN=parsing\nClaims parse_document only"]
        end

        subgraph Host_Storage["Host Persistent Storage (Azure Premium SSD Data Disk: /data)"]
            DiskProjects["/data/projects\n(Bid PDFs, Crops, Quotations)"]
            DiskPricebooks["/data/pricebooks\n(Vendor Sheets: RO on Worker)"]
            DiskMongo["/data/mongo_data\n(Database DB files)"]
            DiskClam["/data/clamav_data\n(Virus definitions cache)"]
            DiskClaude["/data/claude_home\n(Headless CLI config & trust)"]
            DiskCaddy["/data/caddy_data\n(SSL Certificates)"]
        end
    end

    subgraph External_APIs["External API Calls (Outbound Only)"]
        LLM["Anthropic Claude / Amazon Bedrock API\n(Claude 3.5 Sonnet & Haiku)"]
        P21["Hamilton Parker Prophet 21 (P21) ERP\n(Read-Only HTTPS REST Port 443)"]
    end

    Users -->|HTTPS 443 / HTTP 80| Caddy
    Caddy -->|HTTP 3000| Web
    Caddy -->|HTTP 8001| API
    Web -->|HTTP 8001| API

    API -->|TCP 27017| Mongo
    Worker -->|TCP 27017| Mongo
    MongoInit -.->|Initializes rs0| Mongo
    API -->|TCP 3310| ClamAV
  
    API & Worker -.->|Optional HTTP 8000| MinerU
    Parser -.->|HTTP 8000| MinerU
    Parser -.->|TCP 27017| Mongo

    API -->|Mount RW| DiskProjects
    Worker -->|Mount RW| DiskProjects
    API -->|Mount RW| DiskPricebooks
    Worker -->|Mount RO| DiskPricebooks
    Mongo -->|Mount RW| DiskMongo
    ClamAV -->|Mount RW| DiskClam
    Worker -->|Mount RW| DiskClaude
    Caddy -->|Mount RW| DiskCaddy

    Worker -->|Outbound HTTPS 443| LLM
    Worker -->|Outbound HTTPS 443 / VPN| P21
```

---

## 3. Container-by-Container Specification

All services are defined in `infra/docker-compose.yml` and run within the container host:

| Service Name                   | Container Image Source                                                      | Exposed Host Ports                         | Internal Network Port | Volume Mounts                                                                                                                                                                                                              | Purpose                                                                                                   |
| :----------------------------- | :-------------------------------------------------------------------------- | :----------------------------------------- | :-------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------- |
| **`edge-proxy`**       | `caddy:2-alpine` *(or nginx)*                                           | **`80:80`**, **`443:443`** | 80, 443               | •`/data/caddy_data:/data`• `/data/caddy_config:/config`                                                                                                                                                              | Public entry point; TLS 1.3 termination; reverse proxy to`web` and `platform`.                        |
| **`web`**              | `apps/web/Dockerfile` (`cbc-final-web:latest`)                          | None                                       | 3000                  | None (Stateless Next.js standalone)                                                                                                                                                                                        | User-facing estimating dashboard, review queue, and NextAuth session auth.                                |
| **`platform`**         | `apps/backend/Dockerfile` target `api` (`cbc-final-platform:latest`)  | None                                       | 8001                  | •`/data/projects:/app/data/projects` (RW)• `/data/pricebooks:/app/data/pricebooks` (RW)• `../data/reference-library:/app/reference-library:ro`• `../.env:/app/.env:ro`                                         | FastAPI modular monolith API (7 domains), schema migrations, health endpoint.                             |
| **`worker`**           | `apps/backend/Dockerfile` target `worker` (`cbc-final-worker:latest`) | None                                       | None                  | •`/data/projects:/app/data/projects` (RW)• `/data/pricebooks:/app/data/pricebooks:ro`• `../data/reference-library:/app/reference-library:ro`• `/data/claude_home:/home/cbc/.claude`• `../.env:/app/.env:ro` | Background pipeline worker (`WORKER_CLAIM_ALL=1`). Runs headless Claude CLI passes & local MCP servers. |
| **`mongo`**            | `mongo:7` (`cbc-final-mongo`)                                           | None (Internal only)                       | 27017                 | •`/data/mongo_data:/data/db`• `./docker/mongo-keyfile:/mongo-keyfile:ro`• `./docker/mongo-keyfile-entrypoint.sh:/mongo-keyfile-entrypoint.sh:ro`                                                                  | Primary database with`rs0` replica set, auth keyfile, and ACID multi-document transactions.             |
| **`mongo-init`**       | `mongo:7` (`cbc-final-mongo-init`)                                      | None                                       | None                  | •`./docker/mongo-rs-init.sh:/mongo-rs-init.sh:ro`                                                                                                                                                                       | One-off startup container initializing the`rs0` replica set.                                            |
| **`clamav`**           | `clamav/clamav:stable` (`cbc-final-clamav`)                             | None                                       | 3310                  | •`/data/clamav_data:/var/lib/clamav`                                                                                                                                                                                    | Clamd daemon scanning uploaded PDF drawings before storage.                                               |
| **`mineru`** *(GPU)* | `./infra/mineru/Dockerfile` (`cbc-final-mineru`)                        | None                                       | 8000                  | •`/data/mineru_models:/models`                                                                                                                                                                                          | Optional GPU layout parser (NVIDIA CUDA, 4GB SHM).                                                        |
| **`parser`** *(GPU)* | `apps/backend/Dockerfile` target `worker` (`cbc-final-parser`)        | None                                       | None                  | Same as`worker`                                                                                                                                                                                                          | Dedicated worker claiming`parse_document` jobs for MinerU.                                              |

> [!IMPORTANT]
> **Strict Port Isolation:** Notice that ports `27017` (MongoDB), `3310` (ClamAV), `8001` (Platform API), and `8000` (MinerU) have **no host port mappings**. They communicate strictly across the internal Docker bridge network (`cbc-final`). Only `edge-proxy` binds to host ports `80` and `443`.

---

## 4. Azure Host VM & Hardware Requirements

Because all services run inside containers, Azure is used solely as an **unmanaged IaaS container host** (Compute + Disk + Networking):

### 4.1 Azure Virtual Machine Sizing

| Workload Profile                                                                                      | Recommended Azure VM SKU           | vCPU | RAM    | GPU / Hardware                                         | Monthly Estimate (Compute)      |
| :---------------------------------------------------------------------------------------------------- | :--------------------------------- | :--- | :----- | :----------------------------------------------------- | :------------------------------ |
| **Standard Profile (CPU Baseline)***Recommended for 95% of workloads; uses PyMuPDF + Tesseract OCR* | **`Standard_D8s_v5`**      | 8    | 32 GiB | None (High compute & memory for concurrent agent runs) | **~$280 – $340 / month** |
| **High-Spec Profile (GPU MinerU)***For deep layout parsing with MinerU middle.json*                 | **`Standard_NC4as_T4_v3`** | 4    | 28 GiB | 1x NVIDIA T4 (16 GB VRAM)                              | **~$480 – $560 / month** |

### 4.2 Storage: Azure Managed Disks (Replacing Cloud File PaaS)

Instead of Azure Files NFS or Azure Blob Storage, the host attaches high-performance Azure Managed Disks:

| Disk Role           | Azure Disk Type             | Size              | Mount Point on Host | Filesystem     | Contents                                                                                               |
| :------------------ | :-------------------------- | :---------------- | :------------------ | :------------- | :----------------------------------------------------------------------------------------------------- |
| **OS Disk**   | Premium SSD (P10)           | 64 GiB            | `/`               | ext4           | Ubuntu OS, Docker runtime, base container layers.                                                      |
| **Data Disk** | **Premium SSD (P20)** | **512 GiB** | **`/data`** | **ext4** | All persistent container data: Mongo DB files, bid PDF sets, pricebooks, SSL certs, virus definitions. |

#### Storage Directory Layout on Host (`/data`):

```text
/data/
├── app/                  <- Application root / repo clone
│   └── .env              <- Secured environment configuration (chmod 600)
├── projects/             <- Mapped to /app/data/projects (PDF uploads, crops, quotes)
├── pricebooks/           <- Mapped to /app/data/pricebooks (Vendor multiplier sheets)
├── mongo_data/           <- Mapped to /data/db in MongoDB container
├── clamav_data/          <- Mapped to /var/lib/clamav (Virus definitions)
├── claude_home/          <- Mapped to /home/cbc/.claude (CLI credentials & trust)
└── caddy_data/           <- Mapped to /data in Caddy (Let's Encrypt certificates)
```

---

## 5. Security & Isolation Without External Key Vault

In this self-contained design, security is enforced entirely at the host and container layer:

### 5.1 Host-Level Secret Protection

1. **The `.env` File:** Placed at `/data/app/.env` and restricted to `root` and `docker` groups:
   ```bash
   chmod 600 /data/app/.env
   chown root:root /data/app/.env
   ```
2. **Container Injection:** Docker Compose injects environment variables directly from `/data/app/.env` into container process memory. Secrets are never exposed over network endpoints.

### 5.2 Network Isolation & Firewall (Azure NSG)

The Azure Network Security Group (NSG) applied to the VM network interface contains only **three allowed inbound rules**:

| Priority          | Port / Protocol     | Source                   | Destination | Action          | Purpose                                            |
| :---------------- | :------------------ | :----------------------- | :---------- | :-------------- | :------------------------------------------------- |
| **100**     | TCP 443 (HTTPS)     | `0.0.0.0/0`            | Host VM     | **ALLOW** | Estimator access to web application and API proxy. |
| **110**     | TCP 80 (HTTP)       | `0.0.0.0/0`            | Host VM     | **ALLOW** | Automatic HTTP-to-HTTPS redirect & ACME challenge. |
| **120**     | TCP 22 (SSH)        | Azure Bastion / Admin IP | Host VM     | **ALLOW** | Host administration.                               |
| **Default** | **All Ports** | `0.0.0.0/0`            | Host VM     | **DENY**  | Blocks all other ports.                            |

---

## 6. Containerized Ingress: Caddy Edge Proxy

To replace Azure Application Gateway, a containerized Caddy reverse proxy is added to `infra/docker-compose.yml`. Caddy automatically handles SSL certificate acquisition and renewal via Let's Encrypt with zero external configuration.

### 6.1 Caddy Service Definition (Added to `docker-compose.yml`)

```yaml
  edge-proxy:
    image: caddy:2-alpine
    container_name: cbc-final-edge-proxy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./docker/Caddyfile:/etc/caddy/Caddyfile:ro
      - /data/caddy_data:/data
      - /data/caddy_config:/config
    depends_on:
      - web
      - platform
    networks:
      - default
```

### 6.2 Caddyfile Configuration (`infra/docker/Caddyfile`)

```caddyfile
cbc.hamiltonparker.com {
    # Automatic HTTPS via Let's Encrypt
    encode gzip zstd

    # Route Platform API calls
    handle /api/* {
        reverse_proxy platform:8001 {
            header_up Host {host}
            header_up X-Real-IP {remote_host}
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto {scheme}
            transport http {
                response_header_timeout 300s
            }
        }
    }

    # Route Web UI and NextAuth
    handle {
        reverse_proxy web:3000 {
            header_up Host {host}
            header_up X-Real-IP {remote_host}
            header_up X-Forwarded-For {remote_host}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    # Security Headers
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
}
```

---

## 7. Containerized MongoDB Replica Set & Multi-Document Transactions

The application's multi-document ACID transactions (`session.start_transaction()` in `cbc.shared.mongo`) are fully supported by the included containerized replica set:

1. **Authentication Keyfile:** The keyfile `infra/docker/mongo-keyfile` is copied into the container filesystem by `infra/docker/mongo-keyfile-entrypoint.sh` with permissions `400` and ownership `mongodb:mongodb`.
2. **Automated Replica Set Initiation:** The container `mongo-init` executes `infra/docker/mongo-rs-init.sh`:
   ```bash
   mongosh -u cbc -p "$MONGO_ROOT_PASSWORD" --eval 'rs.initiate({_id: "rs0", members: [{_id: 0, host: "mongo:27017"}]})'
   ```
3. **Read-Only Catalog Isolation:** During startup, `cbc.app.main` runs `ensure_readonly_user()`, creating user `cbc_catalog_ro` inside the containerized database. This gives the `catalog` MCP server read-only access with zero write permissions.

---

## 8. Complete Environment Variables Configuration (`/data/app/.env`)

Here is the exact production configuration file placed directly on the host VM at `/data/app/.env`:

```dotenv
# ── MongoDB (Containerized Replica Set rs0) ──────────────────────────────────
# Authenticates over internal Docker network directly to mongo container
MONGODB_URI=mongodb://cbc:COMPLEX_MONGO_PASSWORD_HERE@mongo:27017/cbc_opshub?authSource=admin&replicaSet=rs0
MONGODB_DB=cbc_opshub
MONGO_ROOT_PASSWORD=COMPLEX_MONGO_PASSWORD_HERE
MONGODB_TRANSACTIONS=1
MONGODB_READONLY_PASSWORD=COMPLEX_READONLY_PASSWORD_HERE

# ── Storage Paths (Mounted from /data on Host) ──────────────────────────────
STORAGE_ROOT=/app/data/projects
PRICEBOOK_DIR=/app/data/pricebooks
REFERENCE_DIR=/app/reference-library
TEMPLATES_DIR=/app/templates

# ── Application Secrets ─────────────────────────────────────────────────────
APP_SECRET_KEY=GENERATE_64_CHAR_HEX_KEY_HERE
INTERNAL_API_TOKEN=GENERATE_64_CHAR_HEX_KEY_HERE
INTERNAL_AUTH=jwt
INTERNAL_JWT_SECRET=GENERATE_64_CHAR_HEX_KEY_HERE
SERVICE_AUDIENCE=platform
APP_ENV=production
MAX_UPLOAD_MB=200

# ── Next.js & Web UI Configuration ──────────────────────────────────────────
PLATFORM_URL=http://platform:8001
NEXTAUTH_URL=https://cbc.hamiltonparker.com
AUTH_SECRET=GENERATE_64_CHAR_AUTH_SECRET_HERE
AUTH_TRUST_HOST=true
CORS_ORIGINS=https://cbc.hamiltonparker.com

# ── Anti-Malware (Containerized ClamAV) ──────────────────────────────────────
MALWARE_SCAN=clamd
MALWARE_SCAN_REQUIRED=1
CLAMD_HOST=clamav
CLAMD_PORT=3310

# ── Worker & Claude Code Runtime ─────────────────────────────────────────────
CLAUDE_BIN=claude
# Mandatory: Process mode runs Claude directly inside the worker container
CLAUDE_SANDBOX=process
WORKER_CLAIM_ALL=1
WORKER_POLL_SECONDS=5
WORKER_JOB_TIMEOUT_SECONDS=3600
WORKER_MAX_ATTEMPTS=3
WORKER_CONCURRENCY=1
PIPELINE_DEBOUNCE_SECONDS=60

# ── LLM Provider (Amazon Bedrock or Anthropic Direct) ────────────────────────
# Option A: Amazon Bedrock
AWS_REGION=us-east-1
AWS_BEARER_TOKEN_BEDROCK=YOUR_BEDROCK_API_TOKEN_HERE
ANTHROPIC_MODEL=us.anthropic.claude-sonnet-4-5-20250929-v1:0
ANTHROPIC_DEFAULT_HAIKU_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0

# Option B: Anthropic Direct API (Uncomment if using Anthropic directly)
# ANTHROPIC_API_KEY=sk-ant-api03-YOUR_KEY_HERE

# ── Prophet 21 (P21) Read-Only ERP Integration ──────────────────────────────
# P21_BASE_URL=https://p21-internal.hamiltonparker.com/api
# P21_API_KEY=YOUR_READONLY_P21_KEY_HERE
# P21_TIMEOUT_SECONDS=10
```

---

## 9. Cost Comparison: Pure Containers vs. Managed Cloud PaaS

By eliminating all external cloud services, infrastructure costs are reduced by over **75%**:

| Component                    | Managed Cloud PaaS (Pattern A)           | **100% Container Stack (This Plan)**        | Savings / Month                  |
| :--------------------------- | :--------------------------------------- | :------------------------------------------------ | :------------------------------- |
| **Ingress / WAF**      | Azure App Gateway v2:**$320/mo**   | Containerized Caddy:**$0/mo**               | -$320                            |
| **Database**           | Azure Cosmos DB vCore:**$700/mo**  | Containerized MongoDB 7:**$0/mo**           | -$700                            |
| **File Storage**       | Azure Files NFS Premium:**$90/mo** | Attached Azure Managed SSD:**$75/mo**       | -$15                             |
| **Secrets & Registry** | Key Vault + ACR Premium:**$70/mo** | Local`.env` + Standard ACR: **$20/mo**    | -$50                             |
| **Compute**            | Azure Container Apps:**$280/mo**   | Azure VM (`Standard_D8s_v5`): **$295/mo** | +$15                             |
| **Total Monthly Cost** | **~$1,460 – $2,100 / month**      | **~$390 – $465 / month**                   | **Save ~$1,200/mo (~75%)** |

---

## 10. Step-by-Step Deployment Runbook on Azure

Execute these steps on the newly provisioned Azure Ubuntu 22.04 VM:

### Step 1: Initialize the Attached Data Disk (`/data`)

```bash
# Format attached 512GB data disk (e.g. /dev/sdc or /dev/nvme1n1)
sudo mkfs.ext4 /dev/disk/azure/scsi1/lun0
sudo mkdir -p /data
echo "/dev/disk/azure/scsi1/lun0 /data ext4 defaults,nofail 0 2" | sudo tee -a /etc/fstab
sudo mount -a

# Create application persistent directories
sudo mkdir -p /data/projects /data/pricebooks /data/mongo_data /data/clamav_data \
              /data/claude_home /data/caddy_data /data/caddy_config /data/app
sudo chown -R 1000:1000 /data/projects /data/pricebooks /data/claude_home
```

### Step 2: Install Docker Engine 27 & Docker Compose

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER
```

### Step 3: Deploy Application Stack

```bash
# Clone the repository to /data/app
git clone https://github.com/hamilton-parker/cbc-copilot.git /data/app
cd /data/app

# Place production .env configuration
sudo cp /path/to/secured.env /data/app/.env
sudo chmod 600 /data/app/.env

# Start the complete containerized stack
docker compose -f infra/docker-compose.yml up -d --build
```

### Step 4: Verify Deployment Health

```bash
# 1. Check all containers are running
docker compose -f infra/docker-compose.yml ps

# 2. Check Platform API health
curl -s -f http://localhost:8001/api/health | jq .
# Expected: {"status": "ok", "service": "platform", "database": "up", "catalogIndex": "ready"}

# 3. Check public HTTPS via Caddy
curl -s -I https://cbc.hamiltonparker.com/signin | grep "HTTP/2 200"
```

---

## 11. Conclusion & Benefits for Hamilton Parker CBC

By choosing this pure containerized deployment:

1. **100% Code & Config Parity:** What runs in local staging is identical line-for-line to what runs in production.
2. **Zero Cloud Lock-in:** The entire system can be moved from Azure to AWS, GCP, or on-premises servers with zero code changes.
3. **Simplified Maintenance:** One VM, one Docker Compose file, and one storage volume.
4. **Significant Cost Reduction:** Eliminates over $1,200/month in managed database, storage, and ingress gateway surcharges.
