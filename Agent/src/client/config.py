"""Configuration management for the C2 agent"""
import json
import os
from pathlib import Path
from typing import Dict, Any

class Config:
    """Handles agent configuration"""
    _CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"
    
    if _CONFIG_PATH.exists():
        DEFAULT_CONFIG = json.load(open(_CONFIG_PATH))
    else:
        DEFAULT_CONFIG = {
        "server":  {
            "ip": "10.101.53.67",
            "port": 2222,
            "use_tls": False
        },
        "agent": {
            "reconnect_delay": 30,
            "max_retries": -1,
            "beacon_interval": 60
        },
        "logging":  {
            "enabled": False,
            "file": None,
            "level": "ERROR"
        }
        }



    def __init__(self, config_path: str = None):
        """
        Initialize configuration
        
        Parameters
        ----------
        config_path : str, optional
            Path to JSON config file. If None, uses defaults.
        """
        self.config = self.DEFAULT_CONFIG.copy()
        
        if config_path and os.path.exists(config_path):
            self._load_from_file(config_path)
        else:
            self._load_from_env()
    
    def _load_from_file(self, path: str):
        """Load configuration from JSON file"""
        try:
            with open(path, 'r') as f:
                user_config = json.load(f)
                self._merge_config(user_config)
        except Exception:
            pass
    
    def _load_from_env(self):
        """Load configuration from environment variables."""
        if os.getenv("C2_SERVER_IP"):
            self.config["server"]["ip"] = os.getenv("C2_SERVER_IP")
        if os.getenv("C2_SERVER_PORT"):
            self.config["server"]["port"] = int(os.getenv("C2_SERVER_PORT"))
    
    def _merge_config(self, user_config: Dict[str, Any]):
        """Merge user config with defaults"""
        for section, values in user_config.items():
            if section in self.config and isinstance(values, dict):
                self.config[section].update(values)
            else:
                self.config[section] = values
    
    def get(self, section: str, key: str, default=None):
        """Get configuration value"""
        return self.config.get(section, {}).get(key, default)
    
    @property
    def server_ip(self) -> str:
        return self.config["server"]["ip"]
    
    @property
    def server_port(self) -> int:
        return self.config["server"]["port"]
    
    @property
    def reconnect_delay(self) -> int:
        return self.config["agent"]["reconnect_delay"]
