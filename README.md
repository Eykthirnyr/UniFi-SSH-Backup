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

Install dependencies with `pip install -r requirements.txt`.

## Running

Adjust settings in the **Settings** tab of the web interface. Start the
application with:

```bash
python3 app.py
```

The default web port is `5000` and can be changed in settings.
