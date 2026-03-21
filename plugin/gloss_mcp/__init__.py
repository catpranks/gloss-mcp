import binaryninja as bn

from .server import Server

_server = Server()

_settings = bn.Settings()
_settings.register_group("gloss-mcp", "Gloss MCP")
_settings.register_setting(
    "gloss-mcp.autostart",
    '{"title": "Auto Start", "description": "Automatically start the Gloss MCP server when Binary Ninja opens", "type": "boolean", "default": false, "ignore": ["SettingsProjectScope", "SettingsResourceScope"]}',
)


def _start(bv=None):
    try:
        _server.start()
    except OSError as e:
        bn.log_error(f"gloss-mcp: failed to start: {e}")
        return
    bn.log_info("gloss-mcp: server started")


def _stop(bv=None):
    if _server.stop():
        bn.log_info("gloss-mcp: server stopped")


bn.PluginCommand.register(
    "Gloss MCP\\Start Server", "Start the Gloss MCP server", _start
)
bn.PluginCommand.register(
    "Gloss MCP\\Stop Server", "Stop the Gloss MCP server", _stop
)

if _settings.get_bool("gloss-mcp.autostart"):
    _start()

bn.log_info("gloss-mcp loaded")
