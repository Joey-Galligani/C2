"""
Tool: Command Execution
Executes a system command and returns the result
"""
import subprocess


def execute_command(command: str, timeout: int = 30) -> str:
    """
    Executes a system command
    
    Parameters
    ----------
    command : str
        Command to execute
    timeout : int
        Timeout in seconds (default: 30)
    
    Returns
    -------
    str
        Command result (stdout + stderr)
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        output = result.stdout + result.stderr
        if not output:
            output = "(No output)"
        output = output.replace('\r\n', '\\n').replace('\n', '\\n').replace('\r', '\\r')
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"
