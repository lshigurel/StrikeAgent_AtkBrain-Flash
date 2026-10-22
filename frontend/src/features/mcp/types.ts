export type McpAgentOption = { id:string; enabled:boolean; custom?:boolean };
export type Transport = "stdio"|"streamable_http"|"sse";
export type ServerFields = { id:string; name?:string; enabled:boolean; transport:Transport; command:string; args:string[]; cwd:string; url:string; allowed_agents:string[] };
export type PublicServerConfig = ServerFields & { env_keys:string[]; header_keys:string[] };
export type ServerPatch = ServerFields & { env?:Record<string,string>; headers?:Record<string,string>; env_patch?:Record<string,string|null>; headers_patch?:Record<string,string|null> };
export type PublicMcpConfig = {version:1;revision:number;servers:PublicServerConfig[]};
export type McpConfigPatch = {revision:number;servers:ServerPatch[]};
export type McpTestResult = {ok:boolean;latency_ms:number;tools:{name:string;description:string;inputSchema:Record<string,unknown>}[];error_code?:string};
