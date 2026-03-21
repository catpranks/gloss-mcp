#!/usr/bin/env python3
"""Manual inspection: start harness, exercise tools, print exact wire traffic."""

import json
import socket
import sys
import time

from harness import BinjaHarness

PRINT_TRUNCATE_ROWS = 10


def connect(addr, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(addr)
            return s
        except (ConnectionRefusedError, FileNotFoundError):
            s.close()
            time.sleep(0.5)
    raise TimeoutError(f"MCP socket not available after {timeout}s")


def rpc(sock, method, params=None, *, msg_id=[0]):
    msg_id[0] += 1
    req = {"jsonrpc": "2.0", "id": msg_id[0], "method": method}
    if params is not None:
        req["params"] = params
    return req


def send(sock, req):
    data = json.dumps(req) + "\n"
    sock.sendall(data.encode())


def recv(sock):
    buf = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError("Connection closed")
        buf += chunk
        if b"\n" in buf:
            line, _ = buf.split(b"\n", 1)
            return json.loads(line)


def tool_call(sock, name, arguments=None):
    """Call a tool, printing only the tool-level input/output."""
    args = arguments or {}
    req = rpc(sock, "tools/call", {"name": name, "arguments": args})
    print(f">>> {name}")
    print(json.dumps(args, indent=2))
    send(sock, req)
    resp = recv(sock)
    payload = extract_payload(resp)
    display = truncate_payload(payload)
    print(f"<<< {name}")
    if isinstance(display, str):
        print(display)
    else:
        print(json.dumps(display, indent=2))
    print()
    return payload


def raw_call(sock, method, params=None):
    """Send a raw JSON-RPC call (for initialize etc). No output."""
    req = rpc(sock, method, params)
    send(sock, req)
    return recv(sock)


def extract_payload(resp):
    """Pull the parsed tool payload out of the JSON-RPC envelope."""
    if "error" in resp:
        return {"_rpc_error": resp["error"]}
    result = resp["result"]
    if result.get("isError"):
        return {"_tool_error": result["content"][0]["text"]}
    text = result["content"][0]["text"]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def truncate_payload(payload):
    """Return a display copy, truncated for readability."""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return payload
    LIST_KEYS = ("rows", "code_refs", "data_refs")
    needs_truncation = any(
        isinstance(payload.get(k), list) and len(payload[k]) > PRINT_TRUNCATE_ROWS
        for k in LIST_KEYS
    )
    if not needs_truncation:
        return payload
    payload = dict(payload)
    notes = []
    for k in LIST_KEYS:
        v = payload.get(k)
        if isinstance(v, list) and len(v) > PRINT_TRUNCATE_ROWS:
            total = len(v)
            payload[k] = v[:PRINT_TRUNCATE_ROWS]
            notes.append(f"{k}: {PRINT_TRUNCATE_ROWS}/{total}")
    payload["display_note"] = "Truncated: " + ", ".join(notes)
    return payload


def main():
    il = sys.argv[1] if len(sys.argv) > 1 else "decompile"
    valid = ("disasm", "llil", "mlil", "decompile")
    if il not in valid:
        print(f"Usage: {sys.argv[0]} [{'/'.join(valid)}]")
        sys.exit(1)

    with BinjaHarness() as h:
        print(f"Temp: {h._tmpdir}")
        print(f"MCP socket: {h.socket_addr}")
        print(f"Connecting to MCP socket...")
        sock = connect(h.socket_addr)
        print(f"Connected.\n")

        raw_call(
            sock,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "inspect", "version": "0.0.1"},
            },
        )

        # 1. List binaries (poll until loaded)
        print("Waiting for binary to load...")
        for _ in range(300):
            binaries = tool_call(sock, "list_binaries")
            if binaries:
                break
            time.sleep(0.2)
        else:
            print("No binaries found, exiting.")
            sys.exit(1)

        # 2. Select first binary
        ordinal = binaries[0]["ordinal"]
        tool_call(sock, "select_binary", {"ordinal": ordinal})

        # 3. Binary info
        tool_call(sock, "binary_info")

        # 4. List functions (filter to Entity)
        tool_call(sock, "list_functions")

        # 5. function_at (mid-main address)
        tool_call(sock, "function_at", {"address": "0x40154a"})

        # 6. Fetch the requested IL/disasm for main
        if il == "disasm":
            tool_call(sock, "get_disasm", {"function": "main"})
        elif il == "decompile":
            tool_call(sock, "decompile", {"function": "main"})
        else:
            tool_call(sock, "get_il", {"function": "main", "il": il})

        # 7. Search bytes (function prologue with wildcard)
        tool_call(sock, "search_bytes", {"pattern": "55 ?? 89 e5"})

        # 8. List data vars (vtables)
        tool_call(sock, "list_data_vars", {"match": "vtable"})

        # 9. Read memory at main
        tool_call(sock, "read_memory", {"address": "main", "length": 64})

        # 10. List imports
        tool_call(sock, "list_imports", {})

        # 11. List exports
        tool_call(sock, "list_exports", {})

        sock.close()


if __name__ == "__main__":
    main()
