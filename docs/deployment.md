# Deployment (single Ubuntu VPS)

> Status: configuration is written and validated locally (`docker compose config`,
> `nginx -t` with a test certificate). **No VPS, domain or GitHub deployment
> secrets were available, so nothing has been deployed and there is no live URL.**

## Size

| Resource | Minimum | Why |
|---|---|---|
| CPU | 2 vCPU (4 recommended) | e5-large embedding on CPU; first full index of the Labor Code took ~38 min on a laptop |
| RAM | 4 GB (6–8 recommended) | api 2 GB + worker 2.5 GB limits (ONNX model ≈ 2.2 GB on disk) |
| Disk | 20 GB | images, model cache, PostgreSQL, snapshots, backups |

## 1. Server preparation

```bash
adduser --disabled-password deploy && usermod -aG docker deploy
# Docker Engine + compose plugin: follow https://docs.docker.com/engine/install/ubuntu/
ufw default deny incoming && ufw default allow outgoing
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
```

Docker publishes ports by editing iptables directly, bypassing ufw. That is
why `deploy/docker-compose.prod.yml` publishes **only** nginx 80/443;
PostgreSQL and Redis live on the internal network without host ports.

SSH: key-only login (`PasswordAuthentication no`), no root login.

## 2. Files on the server

```
/opt/lexuz/
  docker-compose.prod.yml   (from deploy/)
  nginx/templates/          (from deploy/nginx/templates/)
  nginx/bootstrap.conf.template
  scripts/                  (from deploy/scripts/)
  certbot/{www,conf}/
  backups/
  .env                      (secrets, chmod 600, never in git)
```

`.env` (production) — start from `.env.example` and set at least:
`APP_IMAGE`, `DOMAIN`, `POSTGRES_PASSWORD`, `GEMINI_API_KEY` (free-tier project, no billing),
`CORS_ORIGINS=[]`, `METRICS_TOKEN`, `DAILY_AI_BUDGET_USD`, `ENABLE_API_DOCS`.

Images are pulled from `ghcr.io/<owner>/lexuz-rag:<git-sha>`. Make the package
public, or `docker login ghcr.io` on the server with a token that has only
`read:packages`.

## 3. First certificate

```bash
cd /opt/lexuz
mkdir -p certbot/www certbot/conf nginx/active
# temporary HTTP-only nginx for the ACME challenge
docker run -d --name nginx-bootstrap -p 80:80 -e DOMAIN=$DOMAIN \
  -v $PWD/nginx/bootstrap.conf.template:/etc/nginx/templates/default.conf.template:ro \
  -v $PWD/certbot/www:/var/www/certbot:ro nginx:1.27.5-alpine
docker compose -f docker-compose.prod.yml --env-file .env run --rm certbot \
  certonly --webroot -w /var/www/certbot -d $DOMAIN --email you@example.com --agree-tos --no-eff-email
docker rm -f nginx-bootstrap
```

Renewal (cron, twice a day):

```
17 3,15 * * * cd /opt/lexuz && docker compose -f docker-compose.prod.yml --env-file .env run --rm certbot renew -q && docker compose -f docker-compose.prod.yml exec nginx nginx -s reload
```

## 4. First start

```bash
cd /opt/lexuz
C="docker compose -f docker-compose.prod.yml --env-file .env"
$C up -d postgres redis
$C run --rm api alembic upgrade head
$C run --rm worker python -m app.cli ingest all      # downloads the model, fetches, indexes
$C up -d
curl -fsS https://$DOMAIN/health/ready
```

Small vertical slice first: it is fine to ingest only
`istemolchilar-huquqlari` (33 articles, minutes) before the Labor Code.

## 5. Continuous deployment

`.github/workflows/cd.yml` runs after the CI workflow succeeds on `main`:

1. builds and pushes `ghcr.io/<repo>:<sha>` (only that commit);
2. `concurrency: production` → one deploy at a time (and `flock` on the server);
3. SSH with `StrictHostKeyChecking=yes` and a pinned `known_hosts`;
4. server runs `scripts/deploy.sh <image>`: backup → `alembic upgrade head`
   → `up -d` → smoke check (`/health/ready`, `/api/v1/documents`, `/`);
5. if the smoke check fails, the **application** is switched back to the
   previous image.

Repository secrets (environment `production`):

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | server address (if unset, CD skips with a notice) |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | private key of a key pair used only for deploys |
| `DEPLOY_KNOWN_HOSTS` | output of `ssh-keyscan -t ed25519 <host>` verified out of band |

Least privilege: restrict the key in `~deploy/.ssh/authorized_keys`:
`command="/opt/lexuz/scripts/deploy.sh $SSH_ORIGINAL_COMMAND",no-port-forwarding,no-pty ssh-ed25519 …`
(then the workflow passes only the image reference).

## 6. Database migrations and rollback

- Application rollback is automatic; **database rollback is not**.
- Migrations follow expand/contract: a release may only *add* nullable
  columns/tables/indexes; dropping or renaming happens in a later release
  after no running version uses the old shape. This keeps the previous image
  compatible with the new schema, which is what makes app rollback safe.
- `alembic downgrade` is tested in CI but must not be used blindly in
  production (it can drop data).
- Restoring from backup (`scripts/restore.sh backups/<file>.dump`) loses
  everything written after the backup (ingestion jobs, usage events).
  Re-run ingestion afterwards; it is idempotent.

## 7. Backups

`scripts/backup.sh` (also run before every deploy) writes a `pg_dump -Fc`
and a tarball of raw source snapshots to `/opt/lexuz/backups`, keeping 14.
Copy them off the server (e.g. `rclone` to object storage) — a backup on the
same disk does not survive disk loss. Test a restore on a scratch server
before relying on it.

## 8. Logs and resources

- Container logs: json-file driver, 10 MB × 5 files per service.
- Memory/CPU limits per service in the compose file; restart `unless-stopped`.
- Watch disk: `docker system df`, `du -sh /opt/lexuz/backups`.
