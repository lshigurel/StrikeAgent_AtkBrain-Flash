"""Administrator-only configuration API, behind the existing application auth gate."""
import time
from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import Field
from .config import StrictModel, ServerConfigPatch, ConfigStore, ConfigConflict
from .transport import McpTransport, TransportError

class ConfigInput(StrictModel):
    revision: int = Field(ge=0)
    servers: list[ServerConfigPatch]

class PrivateValidationRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                # FastAPI normally echoes invalid input, including env/header secrets.
                return JSONResponse(status_code=422,content={"detail":"invalid_mcp_config",
                    "errors":[{"loc":e["loc"],"type":e["type"]} for e in error.errors()]})
        return private_handler

def make_router(store: ConfigStore, transport: McpTransport) -> APIRouter:
    router=APIRouter(prefix="/settings/mcp",route_class=PrivateValidationRoute)

    @router.get("")
    async def get_config():
        try:
            return store.public_config()
        except (ValueError,OSError):
            raise HTTPException(500,"mcp_config_unavailable") from None

    @router.put("")
    async def save_config(body: ConfigInput):
        try:
            store.save(body.servers,body.revision)
            return store.public_config()
        except ConfigConflict:
            raise HTTPException(409,"mcp_config_changed") from None
        except ValueError:
            raise HTTPException(422,"invalid_mcp_config") from None
        except OSError:
            raise HTTPException(500,"mcp_config_unavailable") from None

    @router.post("/{server_id}/test")
    async def test_connection(server_id: str):
        try:
            server=store.get(server_id)
        except KeyError:
            raise HTTPException(404,"mcp_server_not_found") from None
        except (ValueError,OSError):
            raise HTTPException(500,"mcp_config_unavailable") from None
        start=time.monotonic()
        try:
            tools=await transport.describe(server)
            return {"ok":True,"latency_ms":round((time.monotonic()-start)*1000),
                    "tools":[{"name":t.name,"description":t.description,"inputSchema":t.input_schema} for t in tools]}
        except TransportError as error:
            return {"ok":False,"latency_ms":round((time.monotonic()-start)*1000),
                    "tools":[],"error_code":error.code}
    return router

