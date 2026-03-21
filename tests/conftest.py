import json
import socket
import time
from contextlib import asynccontextmanager

import anyio
import pytest
from anyio.streams.text import TextReceiveStream

from mcp.client.session import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from harness import BinjaHarness


@asynccontextmanager
async def unix_client(addr):
    """MCP client transport over abstract Unix socket."""
    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        SessionMessage
    ](0)

    async with await anyio.connect_unix(addr) as sock:

        async def reader():
            try:
                async with read_stream_writer:
                    buffer = ""
                    async for chunk in TextReceiveStream(sock):
                        lines = (buffer + chunk).split("\n")
                        buffer = lines.pop()
                        for line in lines:
                            if not line.strip():
                                continue
                            message = JSONRPCMessage.model_validate_json(line)
                            await read_stream_writer.send(SessionMessage(message))
            except anyio.ClosedResourceError:
                pass

        async def writer():
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json_str = session_message.message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                        await sock.send((json_str + "\n").encode())
            except anyio.ClosedResourceError:
                pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(reader)
            tg.start_soon(writer)
            yield read_stream, write_stream
            tg.cancel_scope.cancel()


@asynccontextmanager
async def mcp_session(addr):
    """Connect to the MCP server and return an initialized ClientSession."""
    async with unix_client(addr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def _wait_for_binary(addr):
    """Poll list_binaries until at least one binary is available."""

    async def _poll():
        for _ in range(300):
            try:
                async with mcp_session(addr) as session:
                    result = await session.call_tool("list_binaries", {})
                    if not result.isError:
                        binaries = json.loads(result.content[0].text)
                        if len(binaries) > 0:
                            return
            except Exception:
                pass
            await anyio.sleep(0.2)
        raise TimeoutError("No binaries appeared in Binary Ninja")

    anyio.run(_poll)


@pytest.fixture(scope="session")
def harness():
    h = BinjaHarness()
    h.start()
    # Wait for MCP server to accept connections
    for _ in range(100):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.connect(h.socket_addr)
            break
        except (ConnectionRefusedError, FileNotFoundError):
            time.sleep(0.1)
    else:
        raise TimeoutError("MCP server did not start")
    # Wait for binary to be loaded in UI
    _wait_for_binary(h.socket_addr)
    yield h
    h.stop()
