import threading
import asyncio
from api import app
from ssh_server import start_ssh_server

def run_api():
    app.run(host='0.0.0.0', port=8000, threaded=True)

if __name__ == "__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    print("API started on http://0.0.0.0:8000")
    
    asyncio.run(start_ssh_server())
