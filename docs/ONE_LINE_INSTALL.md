# One-line install (ParrotOS / Debian / Ubuntu / Raspberry Pi OS, and Windows)

> **Status:** the Windows installer was run end to end on a Windows 11 PC (install, start, upgrade, uninstall). The Linux installer has been syntax-checked and its desktop-shortcut script run, but **has not been run on a real ParrotOS, Debian or Raspberry Pi system yet**: read `get.sh` and `deploy/install.sh` first, and expect small fixes. Nothing here has driven real greenhouse hardware.

## ParrotOS (and other Debian-based systems)

Works on ParrotOS, Debian, Ubuntu and Raspberry Pi OS (anything with `apt` and systemd, Python 3.11+).

**1. Install** (downloads the release from GitHub, installs a systemd service that starts at boot):

```bash
curl -fsSL https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/get.sh | sudo bash
```

**2. Add the desktop shortcut** (run as your normal user, *not* with sudo; adds a desktop icon and an application-menu entry that open the web interface):

```bash
curl -fsSL https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/deploy/add-desktop-shortcut.sh | bash
```

If the desktop asks, choose *Trust and Launch* / *Allow Launching* once.

Then open <http://localhost:8000> and create the administrator with the one-time code from `sudo cat /var/lib/greenhouse/setup_code.txt`.

Options go after `bash -s --`:

| Option | Effect |
|---|---|
| `--demo` | Seed simulated sensors and equipment (try it without hardware). Only applies to an empty database. |
| `--local-only` | Listen on this computer only (`127.0.0.1`) instead of the whole network. **Recommended on a laptop or ParrotOS workstation.** |

```bash
curl -fsSL https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/get.sh | sudo bash -s -- --demo --local-only
```

Settings live in `/etc/greenhouse/greenhouse.env` (`sudo systemctl restart greenhouse` after editing). Re-running the install command upgrades in place and keeps your data (`/var/lib/greenhouse`). Remove with `sudo /opt/greenhouse/deploy/uninstall.sh` (add `--purge-data` to delete the data as well). On a Raspberry Pi the same command works; for a desktop shortcut that points to a Pi from another computer pass its address: `... | bash -s -- http://<pi-address>:8000`.

The interface speaks plain HTTP: keep it on a private network and never forward port 8000 to the internet ([Security](SECURITY.md)).

## Windows 10 / 11

Needs Python 3.11 or newer (`winget install -e --id Python.Python.3.12`, then open a new PowerShell window). No administrator rights needed. In PowerShell:

```powershell
irm https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/install.ps1 | iex
```

This installs to `%LOCALAPPDATA%\GreenhouseControlCenter` and creates a **Greenhouse Control Center** shortcut on the Desktop and in the Start menu. Double-click it: it starts the server (a minimised window in the taskbar; close it to stop) and opens <http://127.0.0.1:8000>. The setup code for the first start is in `%LOCALAPPDATA%\GreenhouseControlCenter\data\setup_code.txt`.

Try it with simulated devices, or allow other computers on your network to connect:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/install.ps1))) -Demo
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/unupunct/GREENHOUSE-CONTROL-CENTER/main/install.ps1))) -Network
```

Re-running the command upgrades and keeps your data. Remove with `powershell -File "$env:LOCALAPPDATA\GreenhouseControlCenter\uninstall.ps1"` (add `-PurgeData` to delete the data too). Windows runs the program in a console window, not as a service, and GPIO / 1-Wire / I2C drivers only exist on Linux: on a PC you can use the planner, shopping list, manuals, encyclopedia, analytics and demo mode, and USB-RS485 (Modbus) sensors; real greenhouse control belongs on the Raspberry Pi.

## What the commands do

Both download the release archive `greenhouse-control-center-<version>.tar.gz` from this repository's GitHub Releases (the prebuilt web interface is inside, so Node.js is not needed), unpack it to a temporary folder, and set up a Python environment from `backend/requirements.txt`. Nothing is installed outside the folders named above, apart from the apt packages listed in `deploy/install.sh` on Linux. To inspect before running, download the script first (`curl -fsSLO <url>` / `irm <url> -OutFile install.ps1`) and read it.
