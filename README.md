# UniFi SSH Backup

This project provides a small Flask web application to fetch backups from a UniFi network console over SSH.  Each day the scheduled job copies the most recent `.unf` file from `/data/unifi/data/backup/autobackup` on the console and stores it under `backups/YYYYMMDD/` on the machine running the app.

The interface exposes two pages:

* **Home** – shows today's result, lets you run a backup immediately, and displays recent SSH output.
* **Settings** – configure console credentials, backup time, e‑mail notifications, retry behaviour, and the web port.

A separate page lists previous backups and allows downloading them.

## Features

- Automatic retrieval of UniFi console backups via SSH using `paramiko`.
- Dated folders for each day's files. If a backup is triggered again on the same day, the new copy is prefixed with the current time.
- When today's file is missing, the app falls back to the newest `.unf` available and notes the date and time it was created.
- Configurable daily schedule with selectable time zone.
- Optional retry when a backup fails with a user‑defined delay.
- SMTP notifications with TLS support. You can send a test email and also test the SSH connection from the settings page.
- Logs written to `logs/app.log` with timestamps in `dd/mm/yyyy` format. Log files rotate every 100&nbsp;000 lines.
- Button in the settings page to download the latest log file.
- Automatic installation of missing Python packages when the app starts.

## Requirements

- Python 3
- Flask
- APScheduler
- paramiko
- pytz

Install the dependencies with:

```bash
pip install -r requirements.txt
```

The application will also attempt to install any missing modules on startup.

## Running

Launch the server using:

```bash
python3 app.py
```

By default it listens on port `5000`. The port can be changed in the settings page; a restart prompt will appear when the port is modified.

Open `http://<host>:<port>/` in your browser to access the interface. Configure the console IP, SSH credentials, backup time, time zone, and optional SMTP settings. Hover over a field for a short description. Flash messages appear briefly at the top when actions succeed or fail.

Backups and log history are stored locally in the repository folder. The "View Backups" page lists the last 100 days with a success or failure note and download links.
