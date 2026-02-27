"""Utility functions for the agent"""
import sys
import os
from datetime import datetime

class Logger:
    """Simple logger that can be disabled for stealth"""
    
    def __init__(self, enabled: bool = False, log_file: str = None):
        self.enabled = enabled
        self.log_file = log_file
    
    def _log(self, level: str, message: str):
        """Internal logging method"""
        if not self.enabled:
            return
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] [{level}] {message}"
        
        if self.log_file:
            try:
                with open(self.log_file, 'a') as f:
                    f.write(log_message + "\n")
            except: 
                pass
        else:
            print(log_message, file=sys.stderr)
    
    def info(self, message: str):
        self._log("INFO", message)
    
    def error(self, message: str):
        self._log("ERROR", message)
    
    def debug(self, message: str):
        self._log("DEBUG", message)


def is_windows() -> bool:
    """Check if running on Windows"""
    return sys.platform.startswith('win')


def is_debugger_present() -> bool:
    """
    Detect if a debugger is attached (anti-debugging)
    
    Returns
    -------
    bool
        True if debugger is detected, False otherwise
    """
    if is_windows():
        try:
            import ctypes
            if ctypes.windll.kernel32.IsDebuggerPresent() != 0:
                return True

            vm_files = [
                "C:\\windows\\System32\\Drivers\\VBoxMouse.sys",
                "C:\\windows\\System32\\Drivers\\vmmouse.sys",
                "C:\\windows\\System32\\Drivers\\vmhgfs.sys",
            ]
            for f in vm_files:
                if os.path.exists(f):
                    return True
        except:
            return False
    return False
