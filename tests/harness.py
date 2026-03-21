import json
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import prctl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP = PROJECT_ROOT / "temp"
TESTS = PROJECT_ROOT / "tests"


class BinjaHarness:
    def __init__(self, extra_plugins=None):
        self.binja_db = TESTS / "target.bndb"
        self.plugin_path = PROJECT_ROOT / "plugin" / "gloss_mcp"
        self.extra_plugins = extra_plugins or []
        self.license_path = Path.home() / ".binaryninja" / "license.dat"

        self._tmpdir = tempfile.mkdtemp(prefix="gloss-mcp-")
        self.xdg_runtime = Path(self._tmpdir) / "xdg"
        self.bn_user_dir = Path(self._tmpdir) / "binja-user"
        self.socket_addr = str(Path(self._tmpdir) / "mcp.sock")
        self.vnc_socket = TEMP / "vnc.sock"
        self.wayland_display = "wayland-0"
        self.wayland_socket = self.xdg_runtime / self.wayland_display

        self._labwc: subprocess.Popen | None = None
        self._binja: subprocess.Popen | None = None

    def start(self):
        self.xdg_runtime.mkdir(mode=0o700)

        # Isolated binja config
        self.bn_user_dir.mkdir()
        license_link = self.bn_user_dir / "license.dat"
        license_link.symlink_to(self.license_path)
        plugins_dir = self.bn_user_dir / "plugins"
        plugins_dir.mkdir()
        dest = plugins_dir / self.plugin_path.name
        dest.symlink_to(self.plugin_path.resolve())
        for p in self.extra_plugins:
            p = Path(p)
            (plugins_dir / p.name).symlink_to(p.resolve())

        settings = self.bn_user_dir / "settings.json"
        settings.write_text(
            json.dumps(
                {
                    "Binja-RPyC.serviceStartOnLoad": True,
                    "gloss-mcp.autostart": True,
                }
            )
        )

        env = os.environ.copy()
        env["WLR_BACKENDS"] = "headless"
        env["WLR_HEADLESS_OUTPUTS"] = "1"
        env["XDG_RUNTIME_DIR"] = str(self.xdg_runtime)
        env.pop("WAYLAND_DISPLAY", None)
        env.pop("DISPLAY", None)

        vnc = os.environ.get("GLOSS_MCP_VNC")
        if vnc:
            self.vnc_socket.unlink(missing_ok=True)
        labwc_cmd = [
            "labwc",
            "-C",
            "/dev/null",
            "-s",
            "wlr-randr --output HEADLESS-1 --custom-mode 1920x1080",
        ]
        if vnc:
            labwc_cmd += ["-S", f"wayvnc -u {self.vnc_socket}"]

        def _deathsig():
            prctl.set_pdeathsig(signal.SIGKILL)

        self._labwc = subprocess.Popen(labwc_cmd, env=env, preexec_fn=_deathsig)

        # Wait for compositor
        for _ in range(50):
            if self.wayland_socket.exists():
                break
            time.sleep(0.1)
        else:
            raise TimeoutError("labwc wayland socket did not appear")

        # Start binja
        binja_env = env.copy()
        binja_env["BN_USER_DIRECTORY"] = str(self.bn_user_dir)
        binja_env["WAYLAND_DISPLAY"] = self.wayland_display
        binja_env["GLOSS_MCP_SOCKET"] = self.socket_addr

        self._binja = subprocess.Popen(
            ["binja", "-n", str(self.binja_db)],
            env=binja_env,
            preexec_fn=_deathsig,
        )

    def _term_or_kill(self, proc):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def stop(self):
        if self._binja:
            self._term_or_kill(self._binja)
        if self._labwc:
            self._term_or_kill(self._labwc)
        try:
            shutil.rmtree(self._tmpdir)
        except Exception as e:
            print(f"warning: failed to clean up {self._tmpdir}: {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
