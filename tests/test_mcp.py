import json

import pytest
from mcp.client.session import ClientSession

from conftest import mcp_session, unix_client


# --- Session ---


@pytest.mark.anyio
async def test_initialize(harness):
    async with unix_client(harness.socket_addr) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            result = await session.initialize()
            assert result.serverInfo.name == "gloss-mcp"


@pytest.mark.anyio
async def test_list_tools(harness):
    async with mcp_session(harness.socket_addr) as session:
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert "list_binaries" in names
        assert "select_binary" in names


@pytest.mark.anyio
async def test_list_binaries(harness):
    async with mcp_session(harness.socket_addr) as session:
        result = await session.call_tool("list_binaries", {})
        assert not result.isError
        binaries = json.loads(result.content[0].text)
        assert len(binaries) >= 1
        entry = binaries[0]
        assert "ordinal" in entry
        assert "filename" in entry
        assert "view_type" in entry
        assert "target.bndb" in entry["filename"]


@pytest.mark.anyio
async def test_select_binary(harness):
    async with mcp_session(harness.socket_addr) as session:
        binaries = json.loads(
            (await session.call_tool("list_binaries", {})).content[0].text
        )
        ordinal = binaries[0]["ordinal"]
        result = await session.call_tool("select_binary", {"ordinal": ordinal})
        assert not result.isError
        info = json.loads(result.content[0].text)
        assert "filename" in info
        assert "view_type" in info
        assert info["ordinal"] == ordinal


@pytest.mark.anyio
async def test_select_binary_unknown(harness):
    async with mcp_session(harness.socket_addr) as session:
        result = await session.call_tool("select_binary", {"ordinal": 999999})
        assert result.isError


@pytest.mark.anyio
async def test_tool_without_select(harness):
    """Calling a tool that requires a binary before select_binary should error."""
    async with mcp_session(harness.socket_addr) as session:
        result = await session.call_tool("list_functions", {})
        assert result.isError
        assert "select_binary" in result.content[0].text


async def _select_first(session):
    """Select the first available binary. Returns ordinal."""
    binaries = json.loads(
        (await session.call_tool("list_binaries", {})).content[0].text
    )
    ordinal = binaries[0]["ordinal"]
    await session.call_tool("select_binary", {"ordinal": ordinal})
    return ordinal


@pytest.mark.anyio
async def test_binary_info(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("binary_info", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["arch"] is not None
        assert data["platform"] is not None
        assert data["entry_point"].startswith("0x")
        assert data["address_size"] in (4, 8)
        # Segments
        assert data["segments"]["header"] == ["start", "end", "perm"]
        assert len(data["segments"]["rows"]) > 0
        seg = data["segments"]["rows"][0]
        assert seg[0].startswith("0x")
        assert all(c in "rwx" for c in seg[2])
        # Sections
        assert data["sections"]["header"] == ["name", "start", "end", "semantics"]
        assert len(data["sections"]["rows"]) > 0
        sec_names = [row[0] for row in data["sections"]["rows"]]
        assert ".text" in sec_names


# --- Navigation ---


@pytest.mark.anyio
async def test_get_xrefs_by_symbol(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_xrefs", {"address": "main"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "function"]
        assert "code_refs" in data
        assert "data_refs" in data
        assert data["target"].startswith("0x")
        # main is called from _start
        assert len(data["code_refs"]) > 0


@pytest.mark.anyio
async def test_get_xrefs_bad_address(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool(
            "get_xrefs", {"address": "nonexistent_symbol_xyz"}
        )
        assert result.isError


@pytest.mark.anyio
async def test_list_functions(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_functions", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "name"]
        assert len(data["rows"]) > 0
        names = [row[1] for row in data["rows"]]
        assert "main" in names


@pytest.mark.anyio
async def test_list_functions_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_functions", {"match": "get_health"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["rows"]) > 0
        # Displayed name is full_name (demangled)
        assert any("get_health" in row[1] for row in data["rows"])


@pytest.mark.anyio
async def test_list_functions_match_mangled(harness):
    """Matching should also work against mangled names."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_functions", {"match": "_ZNK6Entity"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["rows"]) > 0
        # Matched via mangled name, but displayed as demangled
        assert any("Entity" in row[1] for row in data["rows"])


@pytest.mark.anyio
async def test_function_at_by_symbol(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("function_at", {"address": "main"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["address"].startswith("0x")
        assert len(data["functions"]) >= 1
        func = data["functions"][0]
        assert func["name"] == "main"
        assert func["offset"] == "+0x0"


@pytest.mark.anyio
async def test_function_at_mid_function(harness):
    """Mid-function address should resolve with nonzero offset."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        # Use a known mid-main address (second basic block)
        result = await session.call_tool("function_at", {"address": "0x40154a"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        func = data["functions"][0]
        assert func["name"] == "main"
        assert func["offset"] != "+0x0"


@pytest.mark.anyio
async def test_function_at_expression(harness):
    """Address expressions (symbol + offset) should resolve."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("function_at", {"address": "main+4"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        func = data["functions"][0]
        assert func["name"] == "main"
        assert func["offset"] == "+0x4"


@pytest.mark.anyio
async def test_function_at_no_function(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("function_at", {"address": "0x0"})
        assert result.isError


# --- Code ---


@pytest.mark.anyio
async def test_get_disasm(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_disasm", {"function": "main"})
        assert not result.isError
        text = result.content[0].text
        # Header
        assert "; main" in text.split("\n")[0]
        assert "0x" in text.split("\n")[0]
        # Instruction lines: address, hex bytes, text
        insn_lines = [l for l in text.split("\n") if l.startswith("0x")]
        assert len(insn_lines) > 0
        # Each instruction line has hex bytes between address and mnemonic
        for l in insn_lines[:5]:
            parts = l.split()
            # parts[0] is 0xaddr, parts[1] should be hex bytes
            assert all(c in "0123456789abcdef" for c in parts[1])
        # Basic block structure (blank-line separators)
        blocks = [b for b in text.split("\n\n") if b.strip()]
        assert len(blocks) > 1


@pytest.mark.anyio
async def test_get_disasm_by_expression(harness):
    """Function resolved via address expression (symbol+0) should work."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_disasm", {"function": "main+0"})
        assert not result.isError
        assert "; main" in result.content[0].text.split("\n")[0]


@pytest.mark.anyio
async def test_get_disasm_range(harness):
    """Address range should return a subset of basic blocks."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        full = await session.call_tool("get_disasm", {"function": "main"})
        full_blocks = [b for b in full.content[0].text.split("\n\n") if b.strip()]

        # Use mid-function address as end bound to get a prefix
        ranged = await session.call_tool(
            "get_disasm", {"function": "main", "end": "0x40154a"}
        )
        assert not ranged.isError
        ranged_blocks = [b for b in ranged.content[0].text.split("\n\n") if b.strip()]
        assert 0 < len(ranged_blocks) < len(full_blocks)


@pytest.mark.anyio
async def test_get_il_llil_by_name(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_il", {"function": "main", "il": "llil"})
        assert not result.isError
        text = result.content[0].text
        # Header: function name and address
        assert "; main" in text.split("\n")[0]
        assert "0x" in text.split("\n")[0]
        # Has instructions with address prefixes
        lines = [l for l in text.split("\n") if l.startswith("0x")]
        assert len(lines) > 0


@pytest.mark.anyio
async def test_get_il_has_basic_block_structure(harness):
    """LLIL output should have blank-line separators between basic blocks."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_il", {"function": "main", "il": "llil"})
        text = result.content[0].text
        # main has branches, so there should be multiple blocks separated by blank lines
        blocks = [b for b in text.split("\n\n") if b.strip()]
        assert len(blocks) > 1


@pytest.mark.anyio
async def test_get_il_mlil(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("get_il", {"function": "main", "il": "mlil"})
        assert not result.isError
        text = result.content[0].text
        # Header
        assert "; main" in text.split("\n")[0]
        # Has basic block structure (blank-line separators)
        blocks = [b for b in text.split("\n\n") if b.strip()]
        assert len(blocks) > 1
        # Resolved call targets (disassembly_text rendering)
        assert "__printf_chk" in text or "__builtin_memset" in text
        # Has global annotations
        assert "; g_entity_count=0x" in text
        # Has loop markers
        assert "; loop" in text


@pytest.mark.anyio
async def test_get_il_range(harness):
    """Address range should return a subset of IL basic blocks."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        full = await session.call_tool("get_il", {"function": "main", "il": "llil"})
        full_blocks = [b for b in full.content[0].text.split("\n\n") if b.strip()]

        ranged = await session.call_tool(
            "get_il", {"function": "main", "il": "llil", "end": "0x40154a"}
        )
        assert not ranged.isError
        ranged_blocks = [b for b in ranged.content[0].text.split("\n\n") if b.strip()]
        assert 0 < len(ranged_blocks) < len(full_blocks)


@pytest.mark.anyio
async def test_decompile(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("decompile", {"function": "main"})
        assert not result.isError
        text = result.content[0].text
        # Header
        assert "; main" in text.split("\n")[0]
        # Has indented lines (control flow)
        assert any(l.strip() and "    " in l for l in text.split("\n"))
        # Has global annotations
        assert "; g_entities=0x" in text


# --- Data ---


@pytest.mark.anyio
async def test_list_data_vars(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_data_vars", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "name", "type"]
        assert len(data["rows"]) > 0
        # Should contain known globals from target binary
        named = {row[1] for row in data["rows"] if row[1]}
        assert "g_entity_count" in named


@pytest.mark.anyio
async def test_list_data_vars_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_data_vars", {"match": "vtable"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["rows"]) > 0


@pytest.mark.anyio
async def test_list_data_vars_match_mangled(harness):
    """Matching should work against mangled symbol names."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_data_vars", {"match": "_ZTV6Player"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["rows"]) > 0
        # Displayed as demangled
        assert any("Player" in (row[1] or "") for row in data["rows"])


@pytest.mark.anyio
async def test_search_bytes(harness):
    """Search for push rbp; mov rbp, rsp prologue."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("search_bytes", {"pattern": "55 48 89 e5"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["addresses"]) > 0
        for addr in data["addresses"]:
            assert addr.startswith("0x")


@pytest.mark.anyio
async def test_search_bytes_wildcard(harness):
    """Wildcard nibble should still match the prologue."""
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("search_bytes", {"pattern": "55 ?? 89 e5"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["addresses"]) > 0


@pytest.mark.anyio
async def test_search_bytes_no_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool(
            "search_bytes", {"pattern": "de ad be ef de ad"}
        )
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert len(data["addresses"]) == 0


@pytest.mark.anyio
async def test_read_memory_by_symbol(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("read_memory", {"address": "main"})
        assert not result.isError
        text = result.content[0].text
        lines = text.strip().split("\n")
        assert len(lines) > 0
        # Each line: 0xaddr: hexchars
        for line in lines:
            addr_part, hex_part = line.split(": ", 1)
            assert addr_part.startswith("0x")
            assert all(c in "0123456789abcdef" for c in hex_part)


@pytest.mark.anyio
async def test_read_memory_custom_length(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool(
            "read_memory", {"address": "main", "length": 64}
        )
        assert not result.isError
        lines = result.content[0].text.strip().split("\n")
        assert len(lines) == 2  # 64 bytes / 32 per line


@pytest.mark.anyio
async def test_list_strings(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_strings", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "value"]
        assert len(data["rows"]) > 0
        row = data["rows"][0]
        assert len(row) == 2
        assert row[0].startswith("0x")


@pytest.mark.anyio
async def test_list_strings_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        # Use match to narrow results
        result = await session.call_tool("list_strings", {"match": "main"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        for row in data["rows"]:
            assert "main" in row[1].lower()


@pytest.mark.anyio
async def test_list_imports(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_imports", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "name", "module"]
        assert len(data["rows"]) > 0
        # Every row has at least address and name
        for row in data["rows"]:
            assert len(row) >= 2
            assert row[0].startswith("0x")
        # target.bndb is a dynamically-linked ELF; should have libc imports
        names = [row[1] for row in data["rows"]]
        assert any("printf" in n for n in names)


@pytest.mark.anyio
async def test_list_imports_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_imports", {"match": "printf"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        for row in data["rows"]:
            assert "printf" in row[1].lower()


@pytest.mark.anyio
async def test_list_exports(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_exports", {})
        assert not result.isError
        data = json.loads(result.content[0].text)
        assert data["header"] == ["address", "name", "type"]
        assert len(data["rows"]) > 0
        for row in data["rows"]:
            assert len(row) == 3
            assert row[0].startswith("0x")
            assert row[2] in ("func", "data")
        # target binary exports main
        names = [row[1] for row in data["rows"]]
        assert "main" in names


@pytest.mark.anyio
async def test_list_exports_match(harness):
    async with mcp_session(harness.socket_addr) as session:
        await _select_first(session)
        result = await session.call_tool("list_exports", {"match": "main"})
        assert not result.isError
        data = json.loads(result.content[0].text)
        for row in data["rows"]:
            assert "main" in row[1].lower()
