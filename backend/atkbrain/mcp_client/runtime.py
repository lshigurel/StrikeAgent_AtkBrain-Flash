"""Lazy application singleton. Test suites replace it with isolated instances."""
from ..config import settings
from .config import ConfigStore
from .transport import McpTransport
from .bridge import McpBridge
store=ConfigStore(settings.data_dir / "mcp-servers.json")
transport=McpTransport()
def _is_running(pid):
    from ..engine.scheduler import manager
    return manager.is_running(pid)
bridge=McpBridge(store,transport,_is_running)

