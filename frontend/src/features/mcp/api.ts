import { req } from "../../api";
import type { PublicMcpConfig, McpConfigPatch, McpTestResult } from "./types";
export const getMcpConfig = () => req<PublicMcpConfig>("/api/settings/mcp");
export const saveMcpConfig = (input:McpConfigPatch) => req<PublicMcpConfig>("/api/settings/mcp",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(input)});
export const testMcpServer = (id:string) => req<McpTestResult>("/api/settings/mcp/"+encodeURIComponent(id)+"/test",{method:"POST"});

