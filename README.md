# gloss-mcp

Read-only Binary Ninja MCP server.

Other MCP plugins are sloppy vibe code... so I vibe coded my own.

- baseline tools: globals lookups with substring search, asm/LLIL/MLIL/HLIL, xrefs, read_memory
- tasteful, compact tool instructions
- annotates code with function header, addresses, instruction hex bytes, name->address comments
- depends on python stdlib only
- no separate bridge program, use MCP stdin protocol with socat/netcat-openbsd to connect

## instructions

1. Install the plugin
    ```sh
    # or `link`, for development
    scripts/gloss-mcp-install copy
    ```

1. Start Binary Ninja GUI, select Plugins -> Gloss MCP -> Start Server

1. Run the agent
    ```sh
    claude --mcp-config '{"mcpServers":{"gloss-mcp":{"type":"stdio","command":"socat","args":["-", "ABSTRACT-CONNECT:gloss-mcp"]}}}'
    ```

`GLOSS_MCP_SOCKET=/tmp/whatever binaryninja` to specify listening socket. Default is `@gloss-mcp`

## development

Prerequisites

- Binary Ninja distribution in project `temp/binaryninja/`
- `~/.binaryninja/license.dat`
- `git clone https://github.com/hugsy/binja-headless.git ~/src/binja-headless` for the agent to explore binja APIs with interactive.py

```sh
# Start a binja instance and run tests against it
pytest

# Print various tool outputs against the test binary
python tests/inspect.py

# Start a binja instance and expose it via VNC
GLOSS_MCP_VNC=1 python tests/interactive.py
```
