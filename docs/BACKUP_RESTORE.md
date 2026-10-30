# Backup and restore

## What a backup is

A consistent copy of the whole SQLite database made with SQLite's online backup (safe while the application runs): configuration, sensor history and roll-ups, events, alerts, irrigation runs, crops, maintenance, offers, **users and password hashes**, the audit log. It does not include the application code, the OS or `setup_code.txt`. Every backup is integrity-checked, checksummed and described by a manifest (`.json` next to the `.db`). Files are mode 600 in `<data folder>/backups/`.

## Automatic backups

Admin page → Backup and restore. Default: daily at 03:00, keep the newest 7 (automatic and manual are counted separately; "pre-restore" safety copies keep the newest 5). A failed backup raises a critical alert; the health page warns when the newest backup is older than 3 days or when none exists.

**Disk and wear:** each backup is about the size of the database (a 90-day history of 15 sensors at one sample a minute was 148 MB in the benchmark, PERFORMANCE.md), so 7 daily copies need roughly 1 GB and write that volume to the card every night. Use a USB SSD/stick (set "Also copy to folder") or reduce raw retention (`GCC_RETENTION_DAYS`; hourly roll-ups keep the long-term picture at a tiny size).

**Copy backups OFF the Raspberry Pi.** A backup on the same card does not survive a dead card, theft, or fire. The "also copy" folder is the simplest way (a mounted USB drive or network share); a copy failure raises an alert. You can also download any backup from the Admin page (gzip).

## Verify

"Test backup and restore" (Admin page, `POST /api/backup/verify`, and the **Backup and restore** commissioning check) writes a backup, verifies checksum and integrity, opens a *copy* as a database, reads the configuration back and compares the stable tables with the live database. It proves the backup process and file are sound **on this computer**; it does not prove that your off-device copies exist or that a restore onto a new Pi works: do that rehearsal once.

## Restore

Admin page → Restore on a listed backup, or "Restore from a file…" (.db or .db.gz). Steps the application takes:

1. Refuses files that are not SQLite, fail the integrity check, miss required tables or fail their checksum. Nothing changes if refused.
2. Writes a **pre-restore** backup of the current data (so a restore can itself be undone).
3. Switches every output **off** and drops running jobs and manual overrides.
4. Copies the backup into the live database, reloads the engines, clears cached readings.
5. Keeps the **audit trail** continuous (entries newer than the backup are carried over).

Consequences to know: users and sessions come from the backup, so sign in again with an account that existed then; settings, tasks and sensor history after the backup are gone (the pre-restore copy still has them); the e-stop latch is whatever the backup held.

## Restoring onto a new Raspberry Pi

Install the application (INSTALLATION.md), open it, create the administrator with the setup code, then **Restore from a file…** with your off-device backup. Re-check serial/I2C/GPIO access and run the commissioning checklist again (hardware passes are tied to the configuration and must be re-attested for the new installation).

## Manual backup without the application

```bash
sudo apt install -y sqlite3
sudo -u greenhouse sqlite3 /var/lib/greenhouse/greenhouse.db ".backup '/var/lib/greenhouse/manual.db'"
```
