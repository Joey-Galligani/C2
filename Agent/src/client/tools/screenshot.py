"""
Screenshot Tool - Advanced Management (Service & User Session)

This module allows taking screenshots even if the agent is running as a
Windows service (Session 0) by injecting a capture process into the
active user session.
"""

import os
import sys
import time
import ctypes
import tempfile
import subprocess
import logging
from datetime import datetime
from ctypes import wintypes

try:
    import mss
    import mss.tools
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

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

if sys.platform == 'win32':
    wtsapi32 = ctypes.windll.wtsapi32
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    user32 = ctypes.windll.user32

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

def get_active_user_session():
    """Retrieves the ID of the active user session (physical or RDP)."""
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
    except Exception as e:
        logger.error(f"Error enumerating sessions: {e}")
    
    return kernel32.WTSGetActiveConsoleSessionId()

def run_process_as_user(command_line):
    """
    Launches a command in the active user's context via CreateProcessAsUser.
    This is key to bypassing the Session 0 black screen.
    """
    session_id = get_active_user_session()
    if session_id == 0xFFFFFFFF or session_id == 0:
        return False, "No active user session found"

    user_token = wintypes.HANDLE()
    primary_token = wintypes.HANDLE()

    try:
        if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(user_token)):
            return False, f"WTSQueryUserToken failed: {ctypes.get_last_error()}"

        if not advapi32.DuplicateTokenEx(user_token, MAXIMUM_ALLOWED, None, 
                                         SecurityImpersonation, TokenPrimary, ctypes.byref(primary_token)):
            return False, f"DuplicateTokenEx failed: {ctypes.get_last_error()}"

        si = STARTUPINFO()
        si.cb = ctypes.sizeof(STARTUPINFO)
        si.lpDesktop = "winsta0\\default"
        pi = PROCESS_INFORMATION()

        cmd = ctypes.create_unicode_buffer(command_line)

        if not advapi32.CreateProcessAsUserW(
            primary_token, None, cmd, None, None, False,
            CREATE_NO_WINDOW | NORMAL_PRIORITY_CLASS,
            None, None, ctypes.byref(si), ctypes.byref(pi)
        ):
            return False, f"CreateProcessAsUser failed: {ctypes.get_last_error()}"

        kernel32.WaitForSingleObject(pi.hProcess, 15000)
        
        kernel32.CloseHandle(pi.hProcess)
        kernel32.CloseHandle(pi.hThread)
        return True, "Success"

    except Exception as e:
        return False, str(e)
    finally:
        if user_token: kernel32.CloseHandle(user_token)
        if primary_token: kernel32.CloseHandle(primary_token)

def capture_with_mss(filepath):
    """Fast screenshot capture using MSS (Multi-Screen Shot)."""
    if not HAS_MSS:
        raise ImportError("MSS library not found")
        
    with mss.mss() as sct:
        filename = sct.shot(mon=-1, output=filepath)
        return filename

def capture_with_powershell_script(filepath):
    """
    Robust PowerShell script for capture (fallback and injection).
    Uses .NET System.Drawing to avoid external dependencies.
    """
    ps_script = f"""
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
    $bitmap.Save('{filepath.replace(os.sep, '/')}')
    $graphics.Dispose()
    $bitmap.Dispose()
    """
    cmd_bytes = ps_script.encode('utf-16le')
    b64_cmd = __import__('base64').b64encode(cmd_bytes).decode('ascii')
    
    return f"powershell -EncodedCommand {b64_cmd}"

def take_screenshot():
    """
    Main function called by the agent.
    
    Returns:
        tuple: (success (bool), filepath (str), info (str))
    """
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        temp_dir = tempfile.gettempdir()
        filename = f"screenshot_{timestamp}.png"
        filepath = os.path.join(temp_dir, filename)

        is_windows_service = False
        if sys.platform == 'win32':
            sess_id = wintypes.DWORD()
            kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id))
            if sess_id.value == 0:
                is_windows_service = True

        if not is_windows_service and HAS_MSS:
            try:
                capture_with_mss(filepath)
                if os.path.exists(filepath):
                    return True, filepath, "MSS Capture"
            except Exception as e:
                logger.warning(f"Direct MSS failed: {e}")

        if sys.platform == 'win32':
            cmd = capture_with_powershell_script(filepath)
            
            if is_windows_service:
                success, msg = run_process_as_user(cmd)
                if not success:
                    return False, f"Service Injection Failed: {msg}", "0x0"
            else:
                subprocess.run(cmd, shell=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            if os.path.exists(filepath):
                return True, filepath, "PowerShell/Service Capture"
            else:
                return False, "File not created", "0x0"

        return False, "Unsupported platform or method failed", "0x0"

    except Exception as e:
        return False, str(e), "0x0"

if __name__ == "__main__":
    s, p, i = take_screenshot()
    print(f"Success: {s}")
    print(f"Path: {p}")
    print(f"Info: {i}")
