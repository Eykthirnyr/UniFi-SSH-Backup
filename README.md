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

Adjust settings in the **Settings** tab of the web interface. Start the
application with:

```bash
python3 app.py
```

The default web port is `5000` and can be changed in settings. The backup time
and time zone are selected with interactive controls, and hovering any field
shows a helpful tooltip. SMTP settings include an optional TLS checkbox and a
button to send a test email. The application writes detailed logs to
`logs/app.log` and rotates the file every 100000 lines. You can download the
latest log from the settings page.
