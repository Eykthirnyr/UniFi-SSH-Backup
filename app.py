import os
import json
import datetime
import base64
import subprocess
import smtplib
import sys
import time

def _ensure_packages(pkgs):
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
LOG_LINES = []
LOG_LINE_COUNT = 0
LAST_STATUS = {'success': False, 'message': 'No backup yet', 'file': None}

app = Flask(__name__)
app.secret_key = 'change-me'
scheduler = BackgroundScheduler()


def encode_pw(pw: str) -> str:
    return base64.b64encode(pw.encode()).decode()


def decode_pw(pw: str) -> str:
    try:
        return base64.b64decode(pw.encode()).decode()
    except Exception:
        return ''


def log(msg):
    global LOG_LINE_COUNT
    ts_line = f"{datetime.datetime.now().isoformat()} - {msg}"
    print(ts_line)
    LOG_LINES.append(ts_line)
    if len(LOG_LINES) > 100:
        LOG_LINES.pop(0)
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
            'smtp_from': '',
            'smtp_tls': False,
            'send_report': False,
            'web_port': 5000,
            'client_name': 'Client',
            'timezone': 'UTC'
        }
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    if 'ssh_pass' in cfg:
        cfg['ssh_pass'] = decode_pw(cfg['ssh_pass'])
    if 'smtp_pass' in cfg:
        cfg['smtp_pass'] = decode_pw(cfg['smtp_pass'])
    if 'timezone' not in cfg:
        cfg['timezone'] = 'UTC'
    if 'smtp_tls' not in cfg:
        cfg['smtp_tls'] = False
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


def send_mail(subject, body, suppress_errors=True):
    if not config.get('smtp_host') or not config.get('smtp_to'):
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = config.get('smtp_from')
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
    remote_dir = '/data/unifi/data/backup/autobackup'
    files = sftp.listdir(remote_dir)
    today = datetime.date.today().strftime('%Y%m%d')
    candidates = [f for f in files if today in f]
    if not candidates:
        return None
    return sorted(candidates)[-1]


def run_backup():
    global LAST_STATUS
    log('Starting backup')
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(config['ip'], port=int(config['ssh_port']), username=config['ssh_user'], password=config['ssh_pass'])
        sftp = client.open_sftp()
        filename = find_today_backup(sftp)
        if not filename:
            raise Exception('No backup found for today')
        local_dir = os.path.join(BACKUP_ROOT, datetime.date.today().strftime('%Y%m%d'))
        os.makedirs(local_dir, exist_ok=True)
        remote_path = f'/data/unifi/data/backup/autobackup/{filename}'
        local_path = os.path.join(local_dir, filename)
        sftp.get(remote_path, local_path)
        sftp.close()
        client.close()
        LAST_STATUS = {'success': True, 'message': 'Backup successful', 'file': filename}
        log('Backup successful')
        if config.get('send_report'):
            send_mail(f"{config.get('client_name')} UniFi Network Backup : Success",
                      f"Backup {filename} retrieved successfully.")
    except Exception as e:
        LAST_STATUS = {'success': False, 'message': str(e), 'file': None}
        log(f"Backup failed: {e}")
        if config.get('send_report'):
            send_mail(f"WARNING : {config.get('client_name')} UniFi Network Backup : FAILED",
                      f"Backup failed: {e}")


def schedule_job():
    scheduler.remove_all_jobs()
    t = datetime.datetime.strptime(config['backup_time'], '%H:%M').time()
    tz = pytz.timezone(config.get('timezone', 'UTC'))
    scheduler.add_job(run_backup, 'cron', hour=t.hour, minute=t.minute, id='daily', timezone=tz)


schedule_job()
scheduler.start()


@app.route('/test_email', methods=['POST'])
def test_email_route():
    try:
        send_mail(f"{config.get('client_name')} UniFi Backup Test", "Test email", suppress_errors=False)
        flash('Test email sent')
    except Exception as e:
        flash(f'Test email failed: {e}')
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
    return render_template('run.html', status=LAST_STATUS, logs=LOG_LINES, today_files=today_files, today=today_str, current_time=current_time)


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
    entries = []
    if os.path.exists(BACKUP_ROOT):
        for d in sorted(os.listdir(BACKUP_ROOT), reverse=True):
            files = os.listdir(os.path.join(BACKUP_ROOT, d))
            for f in files:
                entries.append({'date': d, 'name': f})
    entries = entries[:100]
    return render_template('list.html', entries=entries)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    global config
    if request.method == 'POST':
        for key in ['ip', 'ssh_port', 'ssh_user', 'ssh_pass', 'backup_time', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'smtp_to', 'smtp_from', 'client_name', 'timezone']:
            config[key] = request.form.get(key, '')
        config['send_report'] = True if request.form.get('send_report') == 'on' else False
        config['smtp_tls'] = True if request.form.get('smtp_tls') == 'on' else False
        config['web_port'] = int(request.form.get('web_port', 5000))
        save_config(config)
        schedule_job()
        flash('Settings saved')
        return redirect(url_for('settings'))
    return render_template('settings.html', config=config)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.get('web_port', 5000))
