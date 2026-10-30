# Installing Greenhouse Control Center

Prerequisite: a prepared Raspberry Pi (RASPBERRY_PI_SETUP.md) or any computer with Python 3.11+. Development on Windows is covered in the README.

**Not yet tested on a Raspberry Pi.** `deploy/install.sh` and `deploy/greenhouse.service` are written but unverified on a Pi; read them first and expect to adjust.

## Security

Every request needs a signed-in user (SECURITY.md). On the first start the web interface asks for the **one-time setup code** in `setup_code.txt` in the data folder (service installs: `sudo cat /var/lib/greenhouse/setup_code.txt`) and creates the administrator. The interface still speaks **plain HTTP**: keep it on a trusted network or put a TLS reverse proxy in front and set `GCC_COOKIE_SECURE=true`. Never forward port 8000 to the internet. Optional firewall (allows SSH and the app only from your LAN; adjust the subnet):

```bash
sudo apt install -y ufw
sudo ufw allow from 192.168.1.0/24 to any port 22
sudo ufw allow from 192.168.1.0/24 to any port 8000
sudo ufw enable
```

Check SSH is allowed *before* enabling, or you will lock yourself out.

## Option 0: release archive (recommended on a Raspberry Pi)

The release archive contains the backend, the **prebuilt** web interface, deploy files and docs, so the Pi needs no Node.js:

```bash
wget https://github.com/unupunct/GREENHOUSE-CONTROL-CENTER/releases/download/v0.9.0/greenhouse-control-center-0.9.0.tar.gz
tar xzf greenhouse-control-center-0.9.0.tar.gz
cd greenhouse-control-center-0.9.0
sudo ./deploy/install.sh
```

Then follow *Option B* below for the service commands. `install.sh` also installs `python3-gpiozero`/`python3-lgpio` from apt (needed for GPIO outputs/inputs) and builds the Python environment from `requirements.txt`. For exactly the versions the release was tested with use `backend/requirements.lock` instead (`pip install -r requirements.lock`); if a pinned version has no wheel for your Pi, fall back to `requirements.txt`. **Untested on a Raspberry Pi.**

## Option A: manual run (good for trying it)

```bash
sudo apt install -y python3 python3-venv git
cd ~ && git clone <your copy of this project> greenhouse   # or copy the folder over
cd greenhouse/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
GCC_SIMULATE=false .venv/bin/python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

The web UI must be built once (`npm install && npm run build` inside `frontend/`, on any computer with Node 20+) and the resulting `frontend/dist` copied into the project; the backend serves it. Browse to `http://<pi-address>:8000`.

`GCC_SIMULATE=false` skips the demo sensor set on a fresh database. Leave it unset to get simulated demo data.

## Option B: systemd service (starts at boot, restarts on failure)

```bash
sudo ./deploy/install.sh
```

The script installs packages, copies the project to `/opt/greenhouse`, creates a `greenhouse` user (with serial/I2C access), builds the Python environment, installs `deploy/greenhouse.service` and enables it. Data lives in `/var/lib/greenhouse/greenhouse.db`.

Useful commands:

```bash
systemctl status greenhouse
journalctl -u greenhouse -f
sudo systemctl restart greenhouse
```

## Backups

Automatic daily backups are on by default (Admin page). Set a copy folder on a USB drive or network share, and read BACKUP_RESTORE.md: backups contain password hashes and must be kept off the Pi and private.

## Optional: Docker

`Dockerfile` and `docker-compose.yml` are provided but were **never built or tested**. Serial, I2C and GPIO access from a container needs device passthrough and extra permissions specific to your Pi.

## Troubleshooting

| Symptom | Check |
|---|---|
| Page does not load | `systemctl status greenhouse`; was `frontend/dist` copied? |
| `/api/...` works but page is blank | the UI was not built (`frontend/dist/index.html` missing) |
| Serial port "permission denied" | user in `dialout` group; restart the service after changes |
| I2C sensor not found | `sudo i2cdetect -y 1`; I2C enabled? wiring? |
| Service keeps restarting | `journalctl -u greenhouse -n 100` |
