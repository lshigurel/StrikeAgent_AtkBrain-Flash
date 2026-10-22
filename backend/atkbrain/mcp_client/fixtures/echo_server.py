import asyncio
import os
import sys
from pathlib import Path
from pydantic import BaseModel
from mcp.server import MCPServer
mcp = MCPServer("test-echo", log_level="CRITICAL")
class Item(BaseModel):
    value: int
@mcp.tool()
def echo(text: str) -> str:
    if os.environ.get("CALL_LOG"):
        with open(os.environ["CALL_LOG"], "a") as f: f.write("echo\n")
    return text
@mcp.tool()
def nested_echo(item: Item) -> dict:
    return item.model_dump()
@mcp.tool()
def error() -> str:
    raise ValueError("fixture error")
@mcp.tool()
async def slow(seconds: float) -> str:
    await asyncio.sleep(seconds)
    return "done"
if os.environ.get("PID_FILE"):
    Path(os.environ["PID_FILE"]).write_text(str(os.getpid()))
if __name__ == "__main__":
    if len(sys.argv) > 1:
        transport = "sse" if len(sys.argv)>2 and sys.argv[2]=="sse" else "streamable-http"
        mcp.run(transport=transport, host="127.0.0.1", port=int(sys.argv[1]))
    else:
        mcp.run()

