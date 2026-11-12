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
nano .env                        # DOMAIN, ACME_EMAIL, GROQ_API_KEY, ADMIN_GITHUB_LOGIN
make secrets prod-secrets        # generates every password and token into .env
```

**GitHub sign-in** (optional; without it, accounts sign in with a password):

1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
   Homepage URL `https://<domain>`, Authorization callback URL
   `https://<domain>/api/auth/github/callback`.
2. **Generate a new client secret**, then put both values in `.env` on the server:
   `GITHUB_CLIENT_ID=...` and `GITHUB_CLIENT_SECRET=...`.
3. GitHub only signs in accounts that already exist (D56). An account matches a GitHub user by
   the GitHub user name an admin gave it, or by a verified GitHub email equal to the account's
   email; the first sign-in records GitHub's numeric user id, which later sign-ins must match
   (so a renamed or recycled user name cannot take the account over). `ADMIN_GITHUB_LOGIN`
   links the admin account; add other people on the **Users** page.

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

### Small servers (1 GB, e.g. Oracle's always-free `VM.Standard.E2.1.Micro`)

Add swap before anything else, and do not build on the server (1/8 of a core, 1 GB: the
frontend build can take an hour or run out of memory). Build on your own machine, which must
have the same CPU architecture (`uname -m`), and stream the images over SSH:

```bash
# on the server, once
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# on your machine, from the repository (again after every update)
deploy/ship-images.sh ubuntu@<server-ip>

# on the server, instead of make prod-up / prod-update
make prod-start
```

Then continue with `make prod-seed` and `make prod-showcase-import` as above. Pages and
investigations are slower than on a larger server: part of the stack runs from swap.

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

## 7. MCP clients (SSH tunnel)

The MCP servers are not on the internet: reach them through an SSH tunnel. Operations always
runs; the read-only Analytics and Knowledge servers are opt-in (on a 1 GB server they compete
with the app for memory).

```bash
# on the server, once
make secrets                              # adds the *_MCP_EXTERNAL_TOKEN values if missing
echo 'COMPOSE_PROFILES=mcp' >> .env       # optional: also start Analytics and Knowledge
make prod-start                           # or make prod-up (recreates what changed)
grep _MCP_EXTERNAL_TOKEN= .env            # the tokens your client needs

# on your machine: keep this running while you use the servers
ssh -N -L 8101:localhost:8101 -L 8102:localhost:8102 -L 8103:localhost:8103 ubuntu@<server-ip>
```

Then register the servers as in the README ("Connect an MCP client"), with the tokens from the
**server's** `.env`. Operations calls are audited as `external-agent`; there is no approve tool.
To turn the read-only servers off again, remove the `COMPOSE_PROFILES` line and run
`docker compose -f docker-compose.prod.yml --profile mcp stop analytics-mcp knowledge-mcp`.

## Operating notes

- **Logs:** `make prod-logs`; container logs rotate at 5 × 20 MB per service.
- **Token budget:** Groq's free tier allows about 200k tokens per model per day. The rate
  limits (`RATE_LIMIT_*`) are sized for it; the Observability page shows the day's use.
  Showcase replays and cache hits cost nothing.
- **Not exposed:** Postgres, the backend and the enterprise mock are reachable only inside the
  Docker network. The MCP servers listen on the server's loopback (127.0.0.1) only, for MCP
  clients over an SSH tunnel (below); the firewall never needs ports 8101-8103.
- **Certificates** live in the `caddy_data` volume. Keep it: deleting it makes Caddy request
  new certificates, and Let's Encrypt limits how many it issues per week.
- **Refreshing the showcase runs** (after an engine change): record them on a development
  machine with the local model, where tokens are free (D59): run the investigations, mark them
  as showcase in the UI, `make showcase-export`, commit `showcase/showcase_runs.json`; then on
  the server `git pull && make prod-showcase-import`. Not on the server: the free Groq quota
  is about ten investigations a day per model.
