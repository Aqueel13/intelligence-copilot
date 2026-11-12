# Deploying Intelligence WatchDog

One server running the whole stack under Docker Compose (`docker-compose.prod.yml`). Caddy is
the only public service: it serves the built frontend, proxies `/api` to the backend, and
obtains and renews the HTTPS certificate itself. Models come from Groq (the server has no GPU).

```
internet ──443──> caddy ──/api──> backend ──> postgres
                    └── static frontend      ├─> operations-mcp ──> enterprise-mock
                                             └─> Groq
                    watcher (monitors every hour) ──> postgres, Groq
```

Target: Oracle Cloud Always Free, Ampere A1 (4 OCPU, 24 GB RAM, arm64), Ubuntu 24.04. Any
Ubuntu server with Docker works the same way; only the firewall step is Oracle-specific.

## 1. Server

1. Create the instance: **Compute → Instances → Create instance**, image Ubuntu 24.04, shape
   `VM.Standard.A1.Flex` with 4 OCPU / 24 GB, a public IPv4 address, your SSH public key, and
   a 100 GB boot volume. "Out of capacity": try another availability domain, or later.
2. Open the web ports in the cloud firewall: the instance's **subnet → Security list → Add
   ingress rules**: source `0.0.0.0/0`, TCP, destination ports `80,443` (and UDP `443` for
   HTTP/3, optional).
3. Point DNS at it: an `A` record for your domain (or subdomain) with the instance's public IP.
   Check with `dig +short <domain>` before step 4 of *Start*: Caddy needs it to get a
   certificate.

## 2. Code

The repository is private, so the server gets a read-only deploy key:

```bash
ssh ubuntu@<server-ip>
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C watchdog-server
cat ~/.ssh/id_ed25519.pub
```

Add that key on GitHub: **repository → Settings → Deploy keys → Add deploy key** (leave
"Allow write access" off). Then:

```bash
git clone git@github.com:Aqueel13/intelligence-copilot.git
cd intelligence-copilot
bash deploy/setup-server.sh      # Docker, firewall, directories; then log out and back in
```

## 3. Configure

```bash
cd intelligence-copilot
cp deploy/env.production.example .env
nano .env                        # DOMAIN, ACME_EMAIL, GROQ_API_KEY
make secrets prod-secrets        # generates every password and token into .env
```

The admin and demo passwords are now in `.env` (`ADMIN_PASSWORD`, `DEMO_PASSWORD`). Keep a
copy in your password manager.

## 4. Start

```bash
make prod-up                     # first build takes several minutes on the ARM CPU
make prod-seed                   # both packs' data, policy documents, accounts (~5 min)
make prod-showcase-import        # the showcase investigations visitors can replay
```

Open `https://<domain>`. The first request may take a few seconds while Caddy obtains the
certificate (`make prod-logs` shows it). Sign in as `ADMIN_EMAIL` with `ADMIN_PASSWORD`.

The data is the same as on a development machine: the generators are deterministic (seed 42),
and the showcase import checks a fingerprint of the data before loading anything.

## 5. Backups

```bash
crontab -e
# add:
15 3 * * *  cd ~/intelligence-copilot && deploy/backup.sh >> backups/backup.log 2>&1
```

Restore a dump into the running database (replaces what is there):

```bash
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < backups/<file>.dump
```

Everything else is reproducible from the repository: the data from the generators, showcase
runs from `showcase/showcase_runs.json`. Copy the backups off the server now and then
(`scp ubuntu@<server-ip>:intelligence-copilot/backups/*.dump .`).

## 6. Updating

```bash
make prod-update                 # git pull, rebuild, restart; migrations run before the backend
```

## Operating notes

- **Logs:** `make prod-logs`; container logs rotate at 5 × 20 MB per service.
- **Token budget:** Groq's free tier allows about 200k tokens per model per day. The rate
  limits (`RATE_LIMIT_*`) are sized for it; the Observability page shows the day's use.
  Showcase replays and cache hits cost nothing.
- **Not exposed:** Postgres, the backend, the MCP servers and the enterprise mock are reachable
  only inside the Docker network. The Analytics and Knowledge MCP servers (for external MCP
  clients) are not started in production.
- **Certificates** live in the `caddy_data` volume. Keep it: deleting it makes Caddy request
  new certificates, and Let's Encrypt limits how many it issues per week.
- **Refreshing the showcase runs** (after an engine change): run the investigations on the
  server, mark them as showcase in the UI, then `make prod-showcase-export` and commit
  `showcase/showcase_runs.json` from a machine with write access to the repository.
