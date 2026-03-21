#!/usr/bin/env python3
import os
import signal
from pathlib import Path
from harness import BinjaHarness

extra_plugins = [Path.home() / "src" / "binja-headless"]

with BinjaHarness(extra_plugins=extra_plugins) as h:
    if os.environ.get("GLOSS_MCP_VNC"):
        print(f"VNC socket: {h.vnc_socket}")
    print(f"MCP socket: {h.socket_addr}")
    print(f"Temp: {h._tmpdir}")
    print("Ctrl-C to stop")
    signal.pause()
