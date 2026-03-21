import errno
import json
import os
import socket
import socketserver
import threading

from .tools import TOOLS

_PROTOCOL_VERSION = "2025-11-25"
SOCKET_ADDR = "@gloss-mcp"


class Session:
    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.bv_ordinal = None

    def run(self):
        try:
            self._run()
        except BrokenPipeError:
            pass

    def _run(self):
        for line in self.rfile:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                self._send(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {e}"},
                    }
                )
                continue
            try:
                resp = self._handle(msg)
            except Exception as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": msg.get("id") if isinstance(msg, dict) else None,
                    "error": {"code": -32600, "message": f"Invalid Request: {e}"},
                }
            if resp is not None:
                self._send(resp)

    def _send(self, msg):
        data = json.dumps(msg) + "\n"
        self.wfile.write(data.encode())
        self.wfile.flush()

    def _handle(self, msg):
        method = msg.get("method")
        msg_id = msg.get("id")

        # Notifications have no id — no response
        if msg_id is None:
            return None

        if method == "initialize":
            return self._initialize(msg_id)
        elif method == "tools/list":
            return self._tools_list(msg_id)
        elif method == "tools/call":
            return self._tools_call(msg_id, msg.get("params", {}))
        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        else:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }

    def _initialize(self, msg_id):
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "gloss-mcp",
                    "version": "0.1.0",
                },
                "instructions": "Prefer get_il (LLIL) over get_disasm for understanding code; disassembly is only needed for raw bytes or encoding details. Lists return first 100 rows; pass full=true for all. Truncated responses include total count.",
            },
        }

    def _tools_list(self, msg_id):
        tools = [
            {
                "name": name,
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for name, t in TOOLS.items()
        ]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}

    def _tools_call(self, msg_id, params):
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                    "isError": True,
                },
            }

        try:
            result = TOOLS[name]["handler"](self, **arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": str(result)}],
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                },
            }


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        Session(self.rfile, self.wfile).run()


class _ThreadingUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def _claim_socket_path(path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.connect(path)
        except OSError as e:
            if e.errno == errno.ECONNREFUSED:
                os.unlink(path)
            elif e.errno != errno.ENOENT:
                raise
        else:
            raise OSError(f"another instance is already listening on {path!r}")


class Server:
    def __init__(self):
        self._server = None
        self._thread = None

    def start(self):
        if self._server is not None:
            return
        addr = os.environ.get("GLOSS_MCP_SOCKET", SOCKET_ADDR)
        if addr.startswith("@"):
            addr = "\0" + addr[1:]
        else:
            _claim_socket_path(addr)
        self._server = _ThreadingUnixServer(addr, _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        if self._server is None:
            return False
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
        self._server = None
        self._thread = None
        return True
