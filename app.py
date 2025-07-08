import os
import json
import datetime
import base64
import subprocess
import smtplib
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, flash
from apscheduler.schedulers.background import BackgroundScheduler
import paramiko

CONFIG_FILE = 'config.json'
BACKUP_ROOT = 'backups'
LOG_LINES = []
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
    print(msg)
    LOG_LINES.append(f"{datetime.datetime.now().isoformat()} - {msg}")
    if len(LOG_LINES) > 100:
        LOG_LINES.pop(0)


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
            'send_report': False,
            'web_port': 5000,
            'client_name': 'Client'
        }
    with open(CONFIG_FILE, 'r') as f:
        cfg = json.load(f)
    if 'ssh_pass' in cfg:
        cfg['ssh_pass'] = decode_pw(cfg['ssh_pass'])
    if 'smtp_pass' in cfg:
        cfg['smtp_pass'] = decode_pw(cfg['smtp_pass'])
    return cfg


def save_config(cfg):
    store = cfg.copy()
    store['ssh_pass'] = encode_pw(store.get('ssh_pass', ''))
    store['smtp_pass'] = encode_pw(store.get('smtp_pass', ''))
    with open(CONFIG_FILE, 'w') as f:
        json.dump(store, f, indent=2)


config = load_config()


def send_mail(subject, body):
    if not config.get('smtp_host') or not config.get('smtp_to'):
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = config.get('smtp_from')
        msg['To'] = config.get('smtp_to')
        with smtplib.SMTP(config.get('smtp_host'), config.get('smtp_port')) as s:
            if config.get('smtp_user'):
                s.starttls()
                s.login(config.get('smtp_user'), config.get('smtp_pass'))
            s.send_message(msg)
    except Exception as e:
        log(f"Failed to send email: {e}")


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
    scheduler.add_job(run_backup, 'cron', hour=t.hour, minute=t.minute, id='daily')


schedule_job()
scheduler.start()


@app.route('/')
def index():
    today_str = datetime.date.today().strftime('%Y%m%d')
    today_dir = os.path.join(BACKUP_ROOT, today_str)
    today_files = []
    if os.path.exists(today_dir):
        today_files = os.listdir(today_dir)
    return render_template('run.html', status=LAST_STATUS, logs=LOG_LINES, today_files=today_files, today=today_str)


@app.route('/trigger')
def trigger():
    run_backup()
    return redirect(url_for('index'))


@app.route('/download/<date>/<name>')
def download(date, name):
    return send_from_directory(os.path.join(BACKUP_ROOT, date), name, as_attachment=True)


@app.route('/list')
def list_backups():
    entries = []
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
        for key in ['ip', 'ssh_port', 'ssh_user', 'ssh_pass', 'backup_time', 'smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'smtp_to', 'smtp_from', 'client_name']:
            config[key] = request.form.get(key, '')
        config['send_report'] = True if request.form.get('send_report') == 'on' else False
        config['web_port'] = int(request.form.get('web_port', 5000))
        save_config(config)
        schedule_job()
        flash('Settings saved')
        return redirect(url_for('settings'))
    return render_template('settings.html', config=config)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=config.get('web_port', 5000))
