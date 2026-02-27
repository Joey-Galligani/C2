"""
Tool: Privilege Escalation Check
Checks privileges and potential escalation vectors
"""
import sys
import subprocess


def _is_windows():
    return sys.platform.startswith('win')


def check_privileges() -> str:
    """
    Checks current privileges and potential escalation vectors
    
    Returns
    -------
    str
        Privilege information
    """
    if not _is_windows():
        return "Error: Only Windows supported for now"
    
    try:
        import ctypes
        
        result = ""

        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        if is_admin:
            result += "Admin privileges detected\n"
        else:
            result += "Running as standard user\n"

        try:
            priv_output = subprocess.run(
                "whoami /priv",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            if priv_output.stdout:
                result += priv_output.stdout
            if priv_output.stderr:
                result += f"Stderr: {priv_output.stderr}"
            if not priv_output.stdout and not priv_output.stderr:
                result += "No privilege information returned"
        except Exception as e:
            result += f"Could not retrieve privileges: {str(e)}"

        result = result.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\n')
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"
