# UniFi SSH Backup

This project provides a small Flask web interface to automatically retrieve
UniFi Network console backups over SSH. Backups are stored in dated folders
under the `backups/` directory. The application can be configured to run a
daily job and optionally send e-mail reports.

## Requirements

- Python 3
- Flask
- APScheduler
- paramiko
- pytz

Install dependencies with `pip install -r requirements.txt`.
The application will also attempt to install any missing dependencies
automatically when started.

## Running

Adjust settings in the **Settings** tab of the web interface. Sections are grouped
in cards for readability, and every field offers a tooltip. Start the
application with:

```bash
python3 app.py
```

The default web port is `5000` and can be changed in settings. The backup time
and time zone are selected with interactive controls, and hovering any field
 shows a helpful tooltip. SMTP settings include an optional TLS checkbox, and
 mutually exclusive options to send a daily report or notify only when a backup fails. A button lets you send a test email, and another tests the SSH
connection to your console. The sender address is taken from your SMTP user so
no separate field is required. The application writes detailed logs to
`logs/app.log` (starting with an "Application started" message) and rotates the
file every 100000 lines. Log timestamps use the `dd/mm/yyyy` format.
Flash messages are displayed briefly and the console on the home page
shows only SSH related operations. You can download the latest log from the
settings page.
If a backup is triggered more than once in the same day, existing files are kept and the new copy is saved with the current time prefixed to its name. You can enable automatic retries on failure and choose the delay between attempts.
The "View Backups" page lists each day with a success or failure note and links
to download any retrieved files.
If today's backup is not found, the application automatically falls back to the
most recent `.unf` file in the `autobackup` folder. The backup and log pages
note the modification time of that file so you know when it was created.
Changing the web port requires a restart; the settings page will prompt you to
restart the application when the port is modified.
