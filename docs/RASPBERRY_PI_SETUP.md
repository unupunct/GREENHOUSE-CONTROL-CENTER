# Raspberry Pi setup

Written from Raspberry Pi's standard tooling; **not yet walked through on a physical Pi with this project**. If a step differs on your image, trust the official Raspberry Pi documentation.

## 1. What to buy

The Planner page (Advanced mode not required) shows the controller recommendation and reasons; the Shopping page lists the Pi, supply, cooler, storage, enclosure and USB-RS485 adapter with a place for real prices. In short: Raspberry Pi 5 (4 GB) or Pi 4 (4 GB), the matching official USB-C supply, active cooling, and high-endurance storage (NVMe SSD preferred over microSD).

## 2. Install Raspberry Pi OS (64-bit)

1. On your computer install **Raspberry Pi Imager** (raspberrypi.com/software).
2. Choose your Pi model → **Raspberry Pi OS (64-bit)** → your storage.
3. Open the OS customisation: set a hostname (e.g. `greenhouse`), your own username and a strong password, Wi-Fi if needed (Ethernet is better), your time zone, and **enable SSH**.
4. Write the card, insert it in the Pi, power on, wait a few minutes.

## 3. Connect over SSH

```bash
ssh <your-user>@greenhouse.local
```

If `.local` names don't resolve, find the Pi's address on your router and use it instead.

## 4. Update the system

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

`apt update` refreshes the package list, `full-upgrade` installs updates, and the reboot applies kernel updates.

## 5. Stable IP address

Prefer a **DHCP reservation in your router** (assign the Pi's address permanently): it needs no configuration on the Pi. Alternatively, with NetworkManager (current Raspberry Pi OS), list connections, then set a static address (replace the example values with your network's):

```bash
nmcli con show
sudo nmcli con mod "Wired connection 1" ipv4.method manual \
  ipv4.addresses 192.168.1.50/24 ipv4.gateway 192.168.1.1 ipv4.dns 192.168.1.1
sudo nmcli con up "Wired connection 1"
```

A wrong address can lock you out; keep a keyboard and screen available the first time.

## 5b. Time zone and clock (important)

Schedules, the daily light integral and reports all use the Pi's local time. A Raspberry Pi starts in UTC unless you change it:

```bash
sudo timedatectl set-timezone Europe/Bucharest   # use your own zone: timedatectl list-timezones
timedatectl                                       # check 'System clock synchronized: yes'
```

A Pi has no battery clock: without network time it starts with a wrong date. The Maintenance page shows the time zone and flags an impossible year.

## 6. Enable the interfaces you use

```bash
sudo raspi-config nonint do_i2c 0        # I2C (SHT3x etc.)
sudo raspi-config nonint do_serial_hw 1  # only if you want the hardware UART; not needed for USB-RS485
```

For 1-Wire (DS18B20) add `dtoverlay=w1-gpio` to `/boot/firmware/config.txt`, then reboot. Details: SENSOR_GUIDE.md.

## 7. Next

Install the application: see INSTALLATION.md.
