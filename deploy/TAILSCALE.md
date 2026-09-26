# Hosting on a private server with Tailscale

The app runs on one always-on Linux server and is reachable **only** from
devices signed in to your Tailscale network. It has no public address, the
server has no open ports, and Tailscale provides HTTPS.

```
teammate's laptop ──Tailscale──▶ https://engine.<tailnet>.ts.net ─▶ 127.0.0.1:3000 (frontend)
                                        /api/v1/* forwarded by the frontend ─▶ api container
                                 (the api, Mongo and Redis are never reachable directly)
```

The steps assume an Oracle Cloud "Always Free" ARM VM running Ubuntu. Any
Ubuntu machine with about 4 GB of RAM or more works the same way from step 2 on.

---

## 1. Create the server

1. Sign up at cloud.oracle.com (a card is needed for verification).
2. **Compute → Instances → Create instance**
   - Image: **Canonical Ubuntu 24.04**
   - Shape: **Ampere (VM.Standard.A1.Flex)**, 2 OCPU / 12 GB is plenty
   - Boot volume: 50 GB or more
   - Upload your SSH public key (`~/.ssh/id_ed25519.pub`)
   - If it says "out of capacity", try another availability domain or region, or retry later.
3. Note the public IP. You only need it for the first login; step 6 closes it.

```bash
ssh ubuntu@<public-ip>
```

## 2. Install Docker, git and Tailscale

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
sudo apt-get install -y git

curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --ssh --hostname engine
```

Open the link `tailscale up` prints and approve the machine. Then, in the
Tailscale admin console under **DNS**:
- turn on **MagicDNS**
- turn on **HTTPS Certificates**

Your tailnet name is shown there. The server is now `engine.<tailnet>.ts.net`.

## 3. Get the code and configure it

The repository is private. Give the server a read-only **deploy key** for this
one repository, rather than signing it in to your whole GitHub account:

```bash
# on the server
ssh-keygen -t ed25519 -N "" -f ~/.ssh/github_deploy -C engine-server
cat ~/.ssh/github_deploy.pub
printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n' >> ~/.ssh/config
```

Add the printed key at github.com/nelbinxav/personalization-engine →
**Settings → Deploy keys → Add deploy key** (leave "Allow write access"
off). Or run this from your laptop, with the key copied into a file:
`gh repo deploy-key add github_deploy.pub -R nelbinxav/personalization-engine -t engine-server`.

```bash
git clone git@github.com:nelbinxav/personalization-engine.git
cd personalization-engine
cp .env.example .env
nano .env
```

In `.env`:

| Setting | Value |
|---|---|
| `APP_SECRET_KEY` | **The same value as your current `.env`** if you are moving existing data (step 7). Otherwise a new one: `python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `COOKIE_SECURE` | `true` |
| `NEXT_PUBLIC_API_URL` | `/` (the default) |
| `BIND_ADDRESS` | `127.0.0.1` |

Leave `ANTHROPIC_API_KEY` unset (see `CLAUDE.md`). Provider keys can be
entered later in Settings.

## 4. Start it and put it on the tailnet

```bash
docker compose up -d --build        # first build takes a few minutes

sudo tailscale serve --bg --https=443 http://127.0.0.1:3000
tailscale serve status
```

## 5. Accounts and Claude

```bash
docker compose exec api python scripts/create_operator.py you@bighammer.ai
```

Then open `https://engine.<tailnet>.ts.net` from a device on the tailnet, sign
in, and connect Claude in **Settings**. For subscription mode:

```bash
docker compose exec -it worker claude auth login
```

## 6. Close the public door

Only do this once `ssh ubuntu@engine` works over Tailscale.

In Oracle: **Networking → Virtual cloud networks → your VCN → Security Lists →
Default** → delete the ingress rule for port **22**. The server now accepts
nothing from the internet. You reach it with `ssh ubuntu@engine` (Tailscale
SSH), and the app only over the tailnet.

## 7. Move your existing data (optional)

On your laptop, from the project folder:

```bash
deploy/backup.sh                                     # writes backups/<stamp>/
scp backups/<stamp>/mongo.archive.gz ubuntu@engine:~/personalization-engine/
```

On the server, with the **same `APP_SECRET_KEY`** in `.env` as the laptop:

```bash
docker compose exec -T mongo mongorestore --archive --gzip --drop < mongo.archive.gz
rm mongo.archive.gz
```

A different key still restores everything, but the stored provider keys will
not decrypt. Re-enter them in Settings.

## 8. Give teammates access

Tailscale admin console → **Users → Invite**. Each person installs Tailscale,
signs in, and opens `https://engine.<tailnet>.ts.net`. Create each person's
app login with `create_operator.py` (step 5).

The free plan limits the number of users. Check the current limit on
tailscale.com/pricing.

## 9. Backups

Nightly at 03:00, keeping 14:

```bash
crontab -e
# add:
0 3 * * * cd ~/personalization-engine && deploy/backup.sh >> backups/backup.log 2>&1
```

Backups on the same server disappear with it. Now and then, copy one to your
laptop:

```bash
scp -r ubuntu@engine:~/personalization-engine/backups/<stamp> .
```

Each backup holds a copy of `.env` (secrets). Keep it somewhere private.

## 10. Updating

```bash
cd ~/personalization-engine
git pull
docker compose up -d --build
```

Jobs that were mid-run when the worker restarted may sit at "Running" with
nothing happening. Cancel them and start again: rows already done are skipped.

---

## Switching to Cloudflare later

Nothing in the app is tied to Tailscale. To move to Cloudflare Tunnel + Access,
point the tunnel at `127.0.0.1:3000`; no `.env` or code change is needed.
Then remove the `tailscale serve` entry with `sudo tailscale serve reset`.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Login page loads, but signing in fails with a network error | `NEXT_PUBLIC_API_URL` is not `/`, or the frontend was not rebuilt after changing it |
| Signed in, but every page bounces back to login | `COOKIE_SECURE=true` over plain http. Use the `https://` address |
| `tailscale serve` complains about certificates | HTTPS Certificates are not enabled in the admin console (step 2) |
