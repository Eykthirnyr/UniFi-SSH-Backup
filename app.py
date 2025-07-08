import os
"""Flask web application to collect UniFi console backups over SSH."""

import json
import datetime
import base64
import subprocess
import smtplib
import sys
import time

def _ensure_packages(pkgs):
    """Install required packages if they are missing."""
    for p in pkgs:
        try:
            __import__(p)
        except ImportError:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', p])

_ensure_packages(['flask', 'APScheduler', 'paramiko', 'pytz'])

import pytz
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from apscheduler.schedulers.background import BackgroundScheduler
import paramiko

CONFIG_FILE = 'config.json'
BACKUP_ROOT = 'backups'
LOG_DIR = 'logs'
LOG_FILE = os.path.join(LOG_DIR, 'app.log')
HISTORY_FILE = 'history.json'
LOG_LINES = []        # all log lines for the log file
CONSOLE_LINES = []    # lines shown in the web console
LOG_LINE_COUNT = 0
RETRY_JOB_ID = None
TIMEZONES = pytz.common_timezones
LAST_STATUS = {'success': False, 'message': 'No backup yet', 'file': None}

app = Flask(__name__)
app.secret_key = 'change-me'
scheduler = BackgroundScheduler()


def encode_pw(pw: str) -> str:
    """Return a base64 encoded string used to store passwords."""
    return base64.b64encode(pw.encode()).decode()


def decode_pw(pw: str) -> str:
    """Decode a previously encoded password value."""
    try:
        return base64.b64decode(pw.encode()).decode()
    except Exception:
        return ''


def log(msg, ssh=False):
    """Log a message to stdout and to the log file.

    If ``ssh`` is True the line is also added to the console view.
    """
    global LOG_LINE_COUNT
    ts_line = f"{datetime.datetime.now().isoformat()} - {msg}"
    print(ts_line)
    LOG_LINES.append(ts_line)
    if len(LOG_LINES) > 100:
        LOG_LINES.pop(0)
    if ssh:
        CONSOLE_LINES.append(ts_line)
        if len(CONSOLE_LINES) > 100:
            CONSOLE_LINES.pop(0)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(ts_line + "\n")
    LOG_LINE_COUNT += 1
    if LOG_LINE_COUNT >= 100000:
        archive = os.path.join(LOG_DIR, f"app_{int(time.time())}.log")
        os.replace(LOG_FILE, archive)
        open(LOG_FILE, 'w').close()
        LOG_LINE_COUNT = 0


def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {
            'ip': '',
            'ssh_port': 22,
            'ssh_user': 'root',
            'ssh_pass': '',
            'backup_time': '22:30',
            'smtp_host': '',
            'smtp_port': 587,
            'smtp_user': '',
            'smtp_pass': '',
            'smtp_to': '',
            'smtp_tls': False,
            'send_report': False,
            'retry_on_fail': False,
            'retry_delay': 30,
            'web_port': 5000,
            'client_name': 'Client',
            'timezone': 'UTC'
        }
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    cfg.pop('smtp_from', None)
    if 'ssh_pass' in cfg:
        cfg['ssh_pass'] = decode_pw(cfg['ssh_pass'])
    if 'smtp_pass' in cfg:
        cfg['smtp_pass'] = decode_pw(cfg['smtp_pass'])
    if 'timezone' not in cfg:
        cfg['timezone'] = 'UTC'
    if 'smtp_tls' not in cfg:
        cfg['smtp_tls'] = False
    if 'retry_on_fail' not in cfg:
        cfg['retry_on_fail'] = False
    if 'retry_delay' not in cfg:
        cfg['retry_delay'] = 30
    return cfg


def save_config(cfg):
    store = cfg.copy()
    store['ssh_pass'] = encode_pw(store.get('ssh_pass', ''))
    store['smtp_pass'] = encode_pw(store.get('smtp_pass', ''))
    with open(CONFIG_FILE, 'w') as f:
        json.dump(store, f, indent=2)


config = load_config()

if os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'r') as f:
        LOG_LINE_COUNT = sum(1 for _ in f)
else:
    os.makedirs(LOG_DIR, exist_ok=True)
    open(LOG_FILE, 'w').close()

log('Application started')


def load_history():
    """Load the per-day backup history from disk."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_history(h):
    """Persist backup history to disk."""
    with open(HISTORY_FILE, 'w') as f:
        json.dump(h, f, indent=2)


history = load_history()


def update_config_from_request(form):
    """Update configuration dictionary from a submitted form."""
    for key in [
        'ip', 'ssh_port', 'ssh_user', 'ssh_pass', 'backup_time',
        'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'smtp_to',
        'client_name', 'timezone', 'retry_delay'
    ]:
        config[key] = form.get(key, '')
    config['send_report'] = True if form.get('send_report') == 'on' else False
    config['smtp_tls'] = True if form.get('smtp_tls') == 'on' else False
    config['retry_on_fail'] = True if form.get('retry_on_fail') == 'on' else False
    config['web_port'] = int(form.get('web_port', 5000))
    save_config(config)
    schedule_job()


def send_mail(subject, body, suppress_errors=True):
    """Send an email using configured SMTP settings."""
    if not config.get('smtp_host') or not config.get('smtp_to'):
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = config.get('smtp_user') or config.get('smtp_to')
        msg['To'] = config.get('smtp_to')
        with smtplib.SMTP(config.get('smtp_host'), config.get('smtp_port')) as s:
            if config.get('smtp_tls'):
                s.starttls()
            if config.get('smtp_user'):
                s.login(config.get('smtp_user'), config.get('smtp_pass'))
            s.send_message(msg)
    except Exception as e:
        log(f"Failed to send email: {e}")
        if not suppress_errors:
            raise


def find_today_backup(sftp):
    """Return today's autobackup filename on the console or None."""
    remote_dir = '/data/unifi/data/backup/autobackup'
    files = sftp.listdir(remote_dir)
    tz = pytz.timezone(config.get('timezone', 'UTC'))
    today = datetime.datetime.now(tz).strftime('%Y%m%d')
    candidates = [f for f in files if today in f]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def run_backup():
    """Retrieve today's backup via SSH and handle success or failure."""
    global LAST_STATUS, RETRY_JOB_ID, history
    tz = pytz.timezone(config.get('timezone', 'UTC'))
    now = datetime.datetime.now(tz)
    today = now.strftime('%Y%m%d')
    log('Starting backup', ssh=True)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        log('Connecting to console...', ssh=True)
        client.connect(config['ip'], port=int(config['ssh_port']), username=config['ssh_user'], password=config['ssh_pass'])
        sftp = client.open_sftp()
        log('Connection established', ssh=True)
        filename = find_today_backup(sftp)
        if not filename:
            raise Exception('No backup found for today')
        local_dir = os.path.join(BACKUP_ROOT, today)
        os.makedirs(local_dir, exist_ok=True)
        remote_path = f'/data/unifi/data/backup/autobackup/{filename}'
        local_path = os.path.join(local_dir, filename)
        if os.path.exists(local_path):
            prefix = now.strftime('%H%M%S_')
            local_path = os.path.join(local_dir, prefix + filename)
        log(f'Downloading {remote_path} to {local_path}', ssh=True)
        sftp.get(remote_path, local_path)
        sftp.close()
        client.close()
        log('Connection closed', ssh=True)
        LAST_STATUS = {'success': True, 'message': 'Backup successful', 'file': filename}
        log('Backup successful', ssh=True)
        # Record success in history and cancel any pending retry
        h = history.setdefault(today, {'success': True, 'files': []})
        h['success'] = True
        h.setdefault('files', []).append(os.path.basename(local_path))
        h.pop('message', None)
        save_history(history)
        if RETRY_JOB_ID:
            try:
                scheduler.remove_job(RETRY_JOB_ID)
            except Exception:
                pass
            RETRY_JOB_ID = None
        if config.get('send_report'):
            send_mail(f"{config.get('client_name')} UniFi Network Backup : Success",
                      f"Backup {filename} retrieved successfully.")
    except Exception as e:
        LAST_STATUS = {'success': False, 'message': str(e), 'file': None}
        log(f"Backup failed: {e}", ssh=True)
        history[today] = {'success': False, 'message': str(e)}
        save_history(history)
        if config.get('send_report'):
            send_mail(f"WARNING : {config.get('client_name')} UniFi Network Backup : FAILED",
                      f"Backup failed: {e}")
        if config.get('retry_on_fail'):
            delay = int(config.get('retry_delay', 30))
            next_time = now + datetime.timedelta(minutes=delay)
            if next_time.date() == now.date():
                if RETRY_JOB_ID:
                    try:
                        scheduler.remove_job(RETRY_JOB_ID)
                    except Exception:
                        pass
                RETRY_JOB_ID = f"retry_{int(time.time())}"
                scheduler.add_job(run_backup, 'date', run_date=next_time, id=RETRY_JOB_ID)
                log(f"Scheduled retry at {next_time.isoformat()}", ssh=True)
            else:
                log('Next day reached, retry aborted', ssh=True)


def schedule_job():
    """Schedule the daily backup job according to current settings."""
    scheduler.remove_all_jobs()
    t = datetime.datetime.strptime(config['backup_time'], '%H:%M').time()
    tz = pytz.timezone(config.get('timezone', 'UTC'))
    scheduler.add_job(run_backup, 'cron', hour=t.hour, minute=t.minute, id='daily', timezone=tz)


schedule_job()
scheduler.start()


@app.route('/test_email', methods=['POST'])
def test_email_route():
    update_config_from_request(request.form)
    try:
        send_mail(f"{config.get('client_name')} UniFi Backup Test", "Test email", suppress_errors=False)
        flash('Test email sent')
    except Exception as e:
        flash(f'Test email failed: {e}')
    return redirect(url_for('settings'))


@app.route('/test_ssh', methods=['POST'])
def test_ssh_route():
    update_config_from_request(request.form)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        log('Testing SSH connection...', ssh=True)
        client.connect(config['ip'], port=int(config['ssh_port']), username=config['ssh_user'], password=config['ssh_pass'], timeout=5)
        client.close()
        flash('SSH connection successful')
        log('SSH connection successful', ssh=True)
    except Exception as e:
        flash(f'SSH connection failed: {e}')
        log(f'SSH connection failed: {e}', ssh=True)
    return redirect(url_for('settings'))


@app.route('/')
def index():
    tz = pytz.timezone(config.get('timezone', 'UTC'))
    now = datetime.datetime.now(tz)
    today_str = now.strftime('%Y%m%d')
    today_dir = os.path.join(BACKUP_ROOT, today_str)
    today_files = []
    if os.path.exists(today_dir):
        today_files = os.listdir(today_dir)
    current_time = now.strftime('%Y-%m-%d %H:%M %Z')
    return render_template('run.html', status=LAST_STATUS, logs=CONSOLE_LINES, today_files=today_files, today=today_str, current_time=current_time)


@app.route('/trigger')
def trigger():
    run_backup()
    return redirect(url_for('index'))


@app.route('/download/<date>/<name>')
def download(date, name):
    return send_from_directory(os.path.join(BACKUP_ROOT, date), name, as_attachment=True)


@app.route('/logs/latest')
def latest_log():
    return send_from_directory(LOG_DIR, os.path.basename(LOG_FILE), as_attachment=True)


@app.route('/list')
def list_backups():
    rows = []
    for d in sorted(history.keys(), reverse=True):
        info = history[d]
        day_dir = os.path.join(BACKUP_ROOT, d)
        files = os.listdir(day_dir) if os.path.exists(day_dir) else []
        rows.append({'date': d, 'success': info.get('success', False), 'message': info.get('message', ''), 'files': files})
    rows = rows[:100]
    return render_template('list.html', entries=rows)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global config
    if request.method == 'POST':
        update_config_from_request(request.form)
        schedule_job()
        flash('Settings saved')
        return redirect(url_for('settings'))
    return render_template('settings.html', config=config, timezones=TIMEZONES)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.get('web_port', 5000))
