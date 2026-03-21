# gloss-mcp

MCP plugin for Binary Ninja. Embedded MCP server (no separate bridge process).

## Architecture

- **Language**: Python (binja plugin)
- **Transport**: JSON-RPC over abstract Unix socket (`@gloss-mcp`). Newline-delimited messages, stdio-style framing. Server starts inside binja GUI, user enables via menu, agent connects locally.
- **Scope**: Per-connection state tied to the active BinaryView.
- **Distribution**: Python package (directory with `__init__.py`). Stdlib only; vendor what we need.
- **Target**: Latest Binary Ninja, latest API. Not version-picky unless forced.

## Design principles

- Minimal, tasteful tool set. No tool spam.
- AST-level deserialization of LLIL/MLIL/HLIL/decompiled code. Do not stringify and re-parse.
- Reference plugins (slop, but useful for API surface discovery):
  - https://github.com/jtang613/BinAssistMCP -- pip-heavy (mcp, hypercorn, pydantic)
  - https://github.com/fosdickio/binary_ninja_mcp -- stdlib HTTP server, zero deps in the plugin itself

## Plugin lifecycle

- Server off by default at startup.
- `gloss-mcp.autostart` setting (boolean, default false) for programmatic/headless use.
- Menu items (`PluginCommand.register`) for manual start/stop.
- UI hooks: `UIContextNotification` from `binaryninjaui` is the correct way to hook UI readiness.
  - `OnContextOpen` fires when the main window is created -- clean signal for "UI is ready."
  - Official example: `binaryninja-api/python/examples/ui_notifications.py`

## Project layout

- `plugin/gloss_mcp/` -- The binja plugin (package)
  - `__init__.py` -- Plugin entry point, runs on binja startup
  - `server.py` -- JSON-RPC session, socket server
  - `tools.py` -- `@tool` decorator, tool registry (`TOOLS` dict), tool implementations
- `tests/` -- Dev/test infrastructure
  - `conftest.py` -- `unix_client` transport, `mcp_session` context manager, `harness` fixture
  - `test_mcp.py` -- Pytest suite (anyio); exercises each tool via MCP client SDK
  - `inspect.py` -- Manual inspection: raw socket calls, prints wire traffic
  - `harness.py` -- `BinjaHarness`: headless binja in captive Wayland compositor
  - `interactive.py` -- Starts harness, prints VNC socket, waits for Ctrl-C
  - `target.cpp` / `target` / `target.bndb` -- Test binary and pre-analyzed database
- `flake.nix` -- Dev shell (FHS env for binja's cpython, Wayland tooling, pytest)

## Testing conventions

- Shared helpers like `_resolve_address` and `_resolve_function` are already exercised by existing tool tests. Don't re-test them for each new tool — only test behavior specific to the tool itself.

## Reference docs

- `docs/reference-tools.md` -- Detailed tool inventory from both reference plugins (API calls, params, return formats, gotchas)
- `temp/binaryninja/` -- Binary Ninja distribution (user provides for development; not checked in). Source of truth for version.
- `~/src/binaryninja-api` -- API repo. Check out `stable/` tag matching the distribution version when it changes.
  - `docs/` -- User guide and dev guide (mkdocs markdown)
  - `python/` -- Python API source with docstrings (Sphinx autodoc source)
- `~/src/binja-headless` -- RPyC backdoor plugin (hugsy/binja-headless)
- `~/src/BinAssistMCP` -- Reference plugin checkout
- `~/src/binary_ninja_mcp` -- Reference plugin checkout

## Dev/test setup

- **Common harness** (`tests/harness.py`): headless binja in captive Wayland compositor.
  Creates temp dir, symlinks plugin, launches with `target.bndb`, `gloss-mcp.autostart` enabled.

- **Interactive harness** (`tests/interactive.py`): long-running, started by the user. Provides:
  - RPyC on `localhost:18812` -- full access to binja's Python VM.
    See `scripts/rpyc_connect.py` for connection pattern (`c`, `bn`, `bv`).
  - MCP socket (path printed at startup)
  - VNC if `GLOSS_MCP_VNC=1` at `temp/vnc.sock`

- **`tests/inspect.py`**: starts its own harness, exercises tools over MCP, prints wire traffic.

- **`pytest`**: starts its own harness per session.

## Tasks

### Tools

- [x] `list_binaries` -- Enumerate open BinaryViews. Connection starts with none selected.
- [x] `select_binary` -- Bind this connection to a BinaryView. Also used to switch.
- [x] `list_functions` -- Optional substring filter.
- [x] `function_at` -- Resolve an address to its containing function(s). (`bv.get_functions_containing`)
- [x] `get_xrefs` -- Cross-references to an address.
- [x] `get_disasm` -- Disassembly for a function.
- [x] `get_il` -- MLIL/LLIL for a function.
- [x] `decompile` -- Decompiled code (HLIL) for a function.
- [x] `read_memory` -- Hexdump at address or by symbol name.
- [x] `list_strings` -- Optional substring filter.
- [x] `list_data_vars` -- Defined data variables.
- [x] `search_bytes` -- Byte pattern search.
- [x] `binary_info` -- Arch, platform, filename, entry point, segment/section map.
- [x] `list_imports` -- Imported symbols.
- [x] `list_exports` -- Exported symbols.

### Misc tasks

- [x] Pagination
- [x] settings.json to autostart plugin server
- [ ] Status bar button to start/stop server

### Deferred (mutation phase)

- rename_function, rename_variables
- set_variable_type, set_function_prototype
- define_types (from C declarations)
- set_comment
- make_function, patch_bytes
