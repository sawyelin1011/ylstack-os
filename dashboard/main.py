# The FlyOS Project by: DigitalPlat Team(Edward Hsing)
# main.py Created by: Edward Hsing(xingyujie50@gmail.com)
# Adapted for YL StackOS — Andronix Edition
import os as _os

# Dynamic base path — prefer /ylstackos, fall back to /flyos for compatibility
_BASE = '/ylstackos' if _os.path.exists('/ylstackos/files') else '/flyos'
_EXT  = '/ylstackosext' if _os.path.exists('/ylstackosext') else '/flyosext'

# Suppress template errors — old routes redirect to React UI
import jinja2 as _jinja2
_MISSING_TEMPLATE_REDIRECT = True

from flask import Flask, render_template, request, redirect, url_for, session, make_response, Response, jsonify
from flask_login import LoginManager, current_user, login_required, UserMixin, login_user, logout_user
from urllib.parse import urlparse
from werkzeug.security import generate_password_hash, check_password_hash
from flask_babel import Babel, gettext, ngettext, pgettext, lazy_gettext
from tools import *
from datetime import timedelta
import secrets
import string
import os
import subprocess
import sqlite3
import requests
from config import *
from datetime import datetime
import random
import shutil
from flask_login.config import USE_SESSION_FOR_NEXT
from queue import Queue
from threading import Thread
output_queue = Queue()


def execute_command(command):
    process = subprocess.Popen(
        command.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True
    )
    for line in iter(process.stdout.readline, ''):
        output_queue.put(line.rstrip())
    process.stdout.close()
    process.wait()

    output_queue.put(None)


def generate_output():
    for output in iter(output_queue.get, None):
        yield "{}\n".format(output)
        output_queue.task_done()

def get_server_ip():
    if server_ip_get_method == 'url_root':
        return request.url_root.split('//', 1)[-1].split(':')[0]
    elif server_ip_get_method == 'host_spilt':
        return request.host.split(':')[0]
    else:
        return request.url_root

def get_locale():
    cookie = request.cookies.get('locale')
    if cookie in ['en', 'es', 'zh', 'ja', 'fr']:
        return cookie
    return request.accept_languages.best_match(['en', 'es', 'zh', 'ja', 'fr'])
def restore_config():
    try:
        import config
        config.server_port
        config.hostname
        config.boot_ssh
        config.boot_vnc
        config.boot_dashboard
        config.boot_code_server
        config.log_message
        config.show_motd
    except:
        config_path = _BASE + '/config.py'
        backup_path = _BASE + '/files/backup/config.py'
        shutil.copy(backup_path, config_path)
class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id
        self.username = ""

app = Flask(__name__)
babel = Babel(app)
app.secret_key = os.urandom(24)

# Handle missing templates — redirect old Jinja2 routes to React UI
from jinja2 import TemplateNotFound as _TemplateNotFound
@app.errorhandler(_TemplateNotFound)
def handle_missing_template(e):
    """Old routes that render missing templates → redirect to React UI."""
    return redirect('/')

@app.errorhandler(500)
def handle_500(e):
    """Return JSON for API routes, redirect for browser routes."""
    if request.path.startswith('/api/'):
        return jsonify({'error': str(e), 'status': 500}), 500
    return redirect('/')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=5)
app.config['USE_SESSION_FOR_NEXT'] = True
babel.init_app(app, locale_selector=get_locale)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

command_thread = None
app.config['LANGUAGES'] = {
    'en': 'English',
    'es': 'Spanish',
    'zh': 'Chinese',
    'ja': 'Japanese',
    'fr': 'French'
}
app.config['BABEL_DEFAULT_LOCALE'] = 'en'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = _BASE + '/translations'

@app.route('/change_language/<language>', methods=['GET'])
def change_language(language):
    if language in ['en', 'es', 'zh', 'ja', 'fr']: 
        response_msg = "Language set to: " + language
        response = make_response(render_template('success.html', info=response_msg))
        response.set_cookie('locale', language)
        return response
    else:
        return "Invalid language code"
no_pwd_login_alert_command = f'adb shell "su -lp 2000 -c \\"cmd notification post -S bigtext -t \'YL StackOS Login Security Alert\' \'{random.randint(10000, 100000)}\' \'A device logged into the dashboard using the no_pwd_login flag. The device has disabled protection. For security, please disable this flag.\'\\""'
# load user config
from config import *
PASSWORDS_FILE = _BASE + '/files/pwd.conf'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id):
        self.id = user_id

# Required user_loader function for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User(user_id)

# Function to check the password
def check_password(password):
    with open(PASSWORDS_FILE, "r") as file:
        stored_password_hash = file.read().strip()
        if check_password_hash(stored_password_hash, password):
            return True
    return False

@app.route('/language/<lang_code>')
def set_language(lang_code):
    session['lang'] = lang_code
    return redirect(request.referrer or url_for('panel'))

@app.route('/legacy_root_disabled')
def redirectmain():
    # Disabled — dashboard_ui blueprint handles / now (serves React SPA)
    return redirect('/')

@app.route('/dashboard')
@login_required
def panel():
    if setup_check() == False:
        return redirect(url_for('setup_default_login'))
    current_date = datetime.now()
    formatted_date = current_date.strftime('%b %d %Y %H:%M')
    battery_remaining = battery_status()
    desktop_opt = request.args.get('desktop_mode')
    ip_addr = get_local_ip()
    if desktop_opt == "true":
        desktop_mode = ''
    else:
        desktop_mode = '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">'
    
    hostname = get_server_ip()
    return render_template('./panel.html',
    desktop_mode=desktop_mode, 
    run_system=run_system, 
    formatted_date=formatted_date,
    battery_remaining=battery_remaining,
    ip_addr=ip_addr,
    hostname=hostname,
    terminal_port=terminal_port
    )

@app.route('/query_files', methods=['POST'])
@login_required
def query_files():
    try:
        path = request.json['path']
        result = subprocess.check_output(f'ls {path}', shell=True).decode()
        return result
    except:
        return 'No such file or directory'
@app.route('/dashboard/home/view')
@login_required
def overview():
    battery_remaining = battery_status()
    
    try:
        url = "https://raw.githubusercontent.com/sawyelin/ylstack-os/master/notices.txt"
        response = requests.get(url, timeout=3)
        notice = response.text
    except:
        notice = 'Failed to load notice: No network connection or System Error'
    storage = get_device_storage()
    ssh = check_ssh_process()
    vnc = check_vnc_process()
    kernel = get_kernel_version()
    framework_status = ylstack_framework_status()
    if framework_status:
        framework_status =  'Running'
    else:
        framework_status = 'Stopped'

    return render_template('./overview.html', notice=notice, storage=storage, ssh=ssh, vnc=vnc, kernel=kernel, framework_status=framework_status, run_system=run_system, battery_remaining=battery_remaining)
@app.route('/dashboard/vnc/view')
@login_required
def vnc_page():
    
    vnc = check_vnc_process()
    if vnc == 'Stopped':
        return 'VNC Service not started'
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{vnc_port}/vnc.html')
@app.route('/dashboard/codeserver/view')
@login_required
def codeserver_page():
    
    code = check_codeserver_process()
    if code == 'Stopped':
        return 'Code Server Service not started'
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{code_server_port}/')
@app.route('/dashboard/terminal/view')
@login_required
def terminal_android_page():
    
    ttyd = check_ttyd_process()
    if ttyd == 'Stopped':
        return 'Web Terminal Service not started'
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{terminal_port}/')

@app.route('/dashboard/terminal_android/view')
@login_required
def terminal_page():
    
    ttyd = check_ttyd_process()
    if ttyd == 'Stopped':
        return 'Web Terminal Service not started'
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{android_terminal_port}/')
@app.route('/dashboard/file_browser/view')
@login_required
def file_browser_view():
    if boot_file_browser != True:
        return 'File Browser Service not started'
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{file_browser_port}/')
@app.route('/dashboard/androidmgr/view')
@login_required
def android_mgr():
    hostname = get_server_ip()
    return render_template('androidmgr.html')
@app.route('/dashboard/apps/wine', methods=['POST','GET'])
@login_required
def apps_wine():
    hostname = get_server_ip()
    if request.method == 'POST':
        hostname = get_server_ip()
        bits = request.form['bits']
        exepath = request.form['exepath']
        geometry = request.form['geometry']
        os.system(f"rm -rf /tmp/.X11-unix/X{wine_port_vnc}")
        os.system(f"rm -rf /tmp/.X{wine_port_vnc}-lock")
        os.system(f"echo '" + _EXT + "/wine/webvnc.sh {bits} {geometry} {exepath}' > /tmp/wine_webvnc_temp.sh && chmod 755 /tmp/wine_webvnc_temp.sh && nohup vncserver :{wine_port_vnc} -geometry {geometry} -localhost no -xstartup '/tmp/wine_webvnc_temp.sh' >> {_BASE}/logs/wine_vnc.log 2>&1 &")
        os.system(f'nohup {_EXT}/novnc/utils/novnc_proxy --vnc localhost:590{wine_port_vnc} --listen 0.0.0.0:{wine_port_web} >> {_BASE}/logs/wine_novnc.log 2>&1 &')
        time.sleep(2)
        return redirect(f'http://{hostname}:{wine_port_web}/vnc.html')
    return render_template('wine.html', hostname=hostname)
@app.route('/dashboard/apps/wine/kill')
@login_required
def apps_wine_kill():
    os.system(f"vncserver -kill :{wine_port_vnc}")
    return redirect('/dashboard/apps/wine')


def api_auth_required(f):
    """Accept Flask session cookie OR X-Token header — used on android action routes."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if current_user.is_authenticated:
            return f(*args, **kwargs)
        token = (request.headers.get('X-Token') or
                 request.headers.get('X-API-Token') or
                 request.args.get('token'))
        if token:
            try:
                valid = open(_BASE + '/files/token/token').read().strip()
                if valid and token == valid:
                    return f(*args, **kwargs)
            except Exception:
                pass
        return jsonify({'error': 'Unauthorized', 'status': 401}), 401
    return decorated


@app.route('/dashboard/androidmgr/usb_tethering')
@login_required
def androidmgr_usb_tethering():
    return render_template('./manager/usb_tethering.html')

@app.route('/dashboard/androidmgr/usb_tethering/launch')
@api_auth_required
def androidmgr_usb_tethering_launch():
    results = os.popen('/usr/bin/adb shell svc usb setFunctions rndis 2>&1').read()
    return jsonify({'ok': True, 'info': f'USB Tethering enabled. {results}'.strip()})

@app.route('/dashboard/androidmgr/android_screen')
@login_required
def androidmgr_android_screen():
    return render_template('./manager/android_screen.html')

@app.route('/dashboard/androidmgr/android_screen/launch')
@api_auth_required
def androidmgr_android_screen_launch():
    hostname = get_server_ip()
    # Kill any existing VNC session on this display first
    os.system(f"/usr/bin/vncserver -kill :{android_screen_port_vnc} 2>/dev/null; sleep 1; true")
    os.system(f"rm -rf /tmp/.X11-unix/X{android_screen_port_vnc} /tmp/.X{android_screen_port_vnc}-lock")
    # Use /flyosext directly — /ylstackosext symlink resolves to an Android-side path
    # that is not valid inside the chroot (/data/local/flyos/rootfs/flyosext doesn't exist in chroot)
    scrcpy_startup = '/flyosext/android/scrcpy.sh'
    vnc_conf = f'-geometry 1280x720 -xstartup {scrcpy_startup} -localhost no'
    os.system(
        f'/usr/bin/setsid /bin/bash -c '
        f'"/usr/bin/vncserver :{android_screen_port_vnc} {vnc_conf} '
        f'>> {_BASE}/logs/android_screen_vnc.log 2>&1" &'
    )
    time.sleep(3)
    # noVNC proxy: --listen takes port only (not host:port); run with /bin/bash (env bash fails in chroot)
    os.system(
        f'/usr/bin/setsid /bin/bash -c '
        f'"/bin/bash {_EXT}/novnc/utils/novnc_proxy '
        f'--vnc localhost:590{android_screen_port_vnc} '
        f'--listen {android_screen_port_web} '
        f'>> {_BASE}/logs/android_screen_novnc.log 2>&1" &'
    )
    time.sleep(2)
    return jsonify({'redirect_url': f'http://{hostname}:{android_screen_port_web}/vnc.html', 'ok': True})
@app.route('/dashboard/androidmgr/android_screen/stop')
@api_auth_required
def ndroidmgr_android_screen_stop():
    os.system(f"vncserver -kill :{android_screen_port_vnc} 2>/dev/null || true")
    os.system(f"/usr/bin/ss -tlnp | /bin/grep {android_screen_port_web} | /usr/bin/awk '{{print $6}}' | /usr/bin/awk -F= '{{print $2}}' | /usr/bin/xargs -r /bin/kill -9 2>/dev/null || true")
    return jsonify({'ok': True})
@app.route('/dashboard/androidmgr/android_screen/redirect')
@login_required
def androidmgr_android_screen_launch_redirect():
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{android_screen_port_web}/vnc.html')

@app.route('/dashboard/network/vnet', methods=['POST','GET'])
def network_vnet():
    if request.method == 'POST':
        cidr = request.form['cidr']
        adapter = request.form['adapter']
        run_shell = f"""
ip link add {adapter} type veth peer name {adapter}-peer
ip addr add {cidr} dev {adapter}
ip link set {adapter} up
        """
        results = os.popen(run_shell).read()
        script_path = f"/boot/scripts/vadapter-{adapter}.sh"
        with open(script_path, "w") as file:
            file.write(run_shell)
        return render_template('./success.html', info=f'Created Finished. Script saved to {script_path} {results}')
    else:
        return render_template('./manager/vnet.html')

@app.route('/dashboard/network/cloudflare', methods=['POST','GET'])
def network_cloudflared():
    if request.method == 'POST':
        token = request.form['token']
        run_shell = f"""
nohup {_EXT}/cloudflared/cloudflared --no-autoupdate tunnel --protocol auto run --token {token} >> {_BASE}/logs/cloudflared_{token}.log 2>&1 &
        """
        results = os.popen(run_shell).read()
        script_path = f"/boot/scripts/cloudflared-{token}.sh"
        with open(script_path, "w") as file:
            file.write(run_shell)
        return render_template('./success.html', info=f'Created Finished. Script saved to {script_path} {results}')
    else:
        return render_template('./manager/cloudflare.html')

@app.route('/dashboard/androidmgr/launch_desktop')
@login_required
def androidmgr_linuxmode():
    return render_template('./manager/linuxmode.html')

@app.route('/dashboard/androidmgr/launch_desktop/launch')
@api_auth_required
def androidmgr_linuxmode_launch():
    # Return JSON so the React frontend can display the log output
    return jsonify({'log': launch_linux_mode(), 'ok': True})

@app.route('/dashboard/androidmgr/launch_desktop/launch/view_logs')
@login_required
def androidmgr_linuxmode_launch_viewlog():
    hostname = get_server_ip()
    logs_path = f'{_BASE}/logs/launch_linux.log'

    with open(logs_path, 'r') as logs:
        logs_read = logs.read()

    text_response = Response(
        response=logs_read,
        status=200,
        mimetype='text/plain'
    )

    return text_response
    
@app.route('/dashboard/notebook/view')
@login_required
def jupyter_notebook():
    hostname = get_server_ip()
    return redirect(f'http://{hostname}:{jupyter_notebook_port}/')
@app.route('/dashboard/about')
@login_required
def about():
    return render_template('about.html', 
        run_system=run_system,
        os_ver=os_ver,
        os_build_channel=os_build_channel,
        cust_build=cust_build)
@app.route('/dashboard/about/license')
@login_required
def about_license():
    return render_template('about_license.html')
@app.route('/dashboard/settings', methods=['GET', 'POST'])
@login_required
def settings_view():
    if request.method == 'POST':
        newconf = request.form.get('conf')
        configfile_write = open(_BASE + '/config.py', 'w')
        configfile_write.write(newconf)
        return '''
<script>
    alert('Saved! Please re-login')
</script>
<meta http-equiv="refresh" content="0;url=/dashboard/settings"> 
        '''
    configfile_read = open(_BASE + '/config.py')
    configfile_read = configfile_read.read()
    with open(_BASE + '/files/token/token', 'r') as read_token:
        readtoken = read_token.read()
    return render_template('settings.html', run_system=run_system, configfile_read=configfile_read, readtoken=readtoken)
@app.route('/settings/update_timezone')
@login_required
def update_timezone_view():
    timezone = request.args.get("timezone")
    next = request.args.get("next")
    os.system(f"sudo ln -sf /usr/share/zoneinfo/{timezone} /etc/localtime")
    os.system("dpkg-reconfigure -f noninteractive tzdata")
    if next is not None:
        return redirect(next)
    return render_template('./success.html', info='You have successfully changed the time zone. If it has not changed, please check the "/etc/timezone" file!')
@app.route('/settings/updateuserpwd')
@login_required
def updateuserpwd():
    username = request.args.get("username")
    passwd = request.args.get("passwd")
    command = f'echo {username}:{passwd} | chpasswd'
    results = subprocess.getoutput(command)

    if results.strip() != '':
        return render_template('./oops.html', info=f'Update password failed, {results}')
    else:
        return render_template('./success.html', info=f'User: {username} password: {passwd} updated successfully! {results}')
@app.route('/auth/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if no_pwd_login == True:
            user_id = 1
            user = User(user_id)
            login_user(user)
            
            os.system(no_pwd_login_alert_command)
            return redirect(url_for('panel'))
        if log_message:
            current_time = datetime.now()
            formatted_time = current_time.strftime("%b %d %H:%M")
            alert_command = f'adb shell "su -lp 2000 -c \\"cmd notification post -S bigtext -t \'YL StackOS Login Security Alert\' \'{random.randint(10000, 100000)}\' \'A device has successfully logged into the YL StackOS dashboard at {formatted_time}, if you are not logged in, please change the password in settings ASAP, (This message can be disabled in advanced settings)\'\\""'
            os.system(alert_command)
        password = request.form.get('password')
        if password == '':
            return render_template('./oops.html', info='Incorrect password')
        if check_password(password):
            user_id = 1  # You can set any user ID or use a more complex logic here
            user = User(user_id)
            login_user(user)
            return redirect(url_for('panel'))
        else:
            return render_template('./oops.html', info='Incorrect password')
    if setup_check() == False:
        return redirect(url_for('setup_default_login'))
    if no_pwd_login == True:
        user_id = 1
        user = User(user_id)
        login_user(user)
        
        os.system(no_pwd_login_alert_command)
        return redirect(url_for('panel'))
    return render_template('./login.html')
@app.route('/dashboard/settings/updatepwd', methods=['POST'])
@login_required
def settings_updatepwd_view():
    if request.method == 'POST':
        passwd = request.form.get('passwd')
        hashpwd = generate_password_hash(passwd)
        file_path = f'{_BASE}/files/pwd.conf'
        try:
            os.remove(file_path)
        except:
            pass
        try:
            with open(file_path, 'w') as pwd_file:
                pwd_file.write(hashpwd)
            return render_template('info.html', info='Password changed!')
        except Exception as e:
            return render_template('info.html', info=f'system error: {e}, please try again')

@app.route('/dashboard/settings/sysupdate/main')
@login_required
def settings_sysupdate_main():
    response = requests.get(sys_update_check_server)
    if response.status_code == 200:
        latest_ver = response.text
    else:
        latest_ver = f"No internet or unable to connect to update server, Status code: {response.status_code}"
    try:
        import sysconf
        latest_ver = float(latest_ver)
        os_ver = float(sysconf.os_ver)

        if latest_ver == os_ver:
            sysupdate_info = '''
            <div class="alert alert-success" role="alert">
            <p><b>Great! You are on the latest version</b></p>
            </div>
            '''
        elif latest_ver > os_ver:
            sysupdate_info = '''
            <div class="alert alert-warning" role="alert">
            <p><b>New version found!</b></p>
            </div>
            '''
        else:
            sysupdate_info = '''
            <div class="alert alert-danger" role="alert">
            <p><b>Outdated version detected</b></p>
            </div>
            '''

    except ValueError:
        sysupdate_info = '''
        <div class="alert alert-danger" role="alert">
        <p><b>Incorrect version format</b></p>
        </div>
        '''

    return render_template('./settings/system_update.html',
    os_ver=os_ver,
    os_build_channel=os_build_channel,
    cust_build=cust_build,
    latest_ver=latest_ver,
    sysupdate_info=sysupdate_info
    )

@app.route('/auth/login/otplogin', methods=['GET', 'POST'])
def otpcode_login():
    if request.method == 'POST':
        getcode = request.form.get('password')
        read_otp = open(_BASE + '/files/temp/otp', 'r')
        read_otp = read_otp.read()    
        if getcode == read_otp:
            user_id = 1
            user = User(user_id)
            login_user(user)
            return redirect(url_for('panel'))
        else:
            return render_template('./oops.html', info='Incorrect one-time password, Please regenerate and try again')
    else:
        if setup_check() == False:
            return redirect(url_for('setup_default_login'))
        otp_code = random.randint(10000, 100000)
        save_otp = open(_BASE + '/files/temp/otp', 'w')
        save_otp.write(str(otp_code))
        send_android_msg('YL StackOS Login OTP', f'Your one-time login password is: {otp_code}, valid for this page session', 5000)
        return render_template('otplogin.html')
@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# first setup
from functools import wraps
setup_lock_text = 'You have already done the setup, to do it again, delete the file'
def check_setup(func):
    @wraps(func)
    def decorated_function(*args, **kwargs):
        if setup_check():
            return render_template('./oops.html', info=setup_lock_text)
        return func(*args, **kwargs)
    return decorated_function

@app.route("/setup/login")
@check_setup
def setup_default_login():
    user_id = 1
    user = User(user_id)
    login_user(user)
    return redirect(url_for('setup_welcome'))

@app.route("/setup/welcome")
@login_required
@check_setup
def setup_welcome():
    return render_template('./setup/welcome.html')

@app.route("/setup/welcome/rocket")
@login_required
@check_setup
def setup_welcome_rocket():
    return render_template('./setup/welcome_rocket.html')

@app.route("/setup/languages")
@login_required
@check_setup
def setup_languages():
    return render_template('./setup/languages.html')

@app.route("/setup/timezone")
@login_required
@check_setup
def setup_timezone():
    return render_template('./setup/timezone.html')

@app.route("/setup/setylstackospwd")
@login_required
@check_setup
def setup_syspwd():
    return render_template('./setup/setpwd.html')

@app.route("/setup/done")
@login_required
@check_setup
def setup_done():
    gen_newtoken()
    os.system(f'touch {_BASE}/files/setup/setup_lock')
    return render_template('./setup/done.html')

def logout():
    logout_user()
    return redirect(url_for('login'))


# service api
def require_token(func):
    with open(_BASE + '/files/token/token', 'r') as tokenfile:
        valid_token = tokenfile.read().strip() 

    def wrapper(*args, **kwargs):
        token = request.args.get('token')
        if token != valid_token:
            return jsonify({"status": 401, "error": "Unauthorized", "message": "Invalid token"}), 401
        return func(*args, **kwargs)

    return wrapper


@app.route("/api/get_service_code_server")
def api_get_service_code_server():
    return check_codeserver_process()

@app.route("/api/get_service_ssh")
def api_get_service_ssh():
    return check_ssh_process()

@app.route("/api/get_service_jupyter")
def api_get_service_jupyter():
    return check_jupyter_process()

@app.route("/api/send_msg")
@require_token
def api_send_android_msg():
    title = request.args.get('title')
    msg = request.args.get('msg')
    msgid = request.args.get('msgid')
    send_android_msg(title, msg, msgid)

    response_data = {
        "status": 200,
        "message": "ok",
        "title": title,
        "msg": msg,
        "msgid": msgid
    }

    return jsonify(response_data), 200

@app.route('/api/system/cmd', endpoint='api_sys_cmd_endpoint')
@require_token
def api_sys_cmd():
    command = request.args.get('command')
    if command:
        command_thread = Thread(target=execute_command, args=(command,))
        command_thread.start()

    return Response(generate_output(), mimetype='text/event-stream')

# reset token
def generate_random_token(length=16):
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token

@app.route("/api/token/reset")
@login_required
def api_token_reset():
    random_token = generate_random_token(20)
    try:
        token_path = _BASE + '/files/token/token'
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, 'w') as tokenfile:
            tokenfile.write(random_token)
        return jsonify({'token': random_token, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route("/api/token/get")
@login_required
def api_token_get():
    try:
        with open(_BASE + '/files/token/token', 'r') as f:
            return jsonify({'token': f.read().strip()})
    except Exception:
        return jsonify({'token': ''})
    

def generate_random_token(length=16):
    alphabet = string.ascii_letters + string.digits
    token = ''.join(secrets.choice(alphabet) for _ in range(length))
    return token

if __name__ == '__main__':
    restore_config()
    app.run(host=dashboard_host_addr, port=server_port, debug={dev_server_debug})