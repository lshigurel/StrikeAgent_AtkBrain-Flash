export type ToolRule = { name:string; roles:("recon"|"web-exploit")[]; profile:"pure"|"http_url"; target_pointers:string[] };
export type ServerFields = { id:string; enabled:boolean; transport:"stdio"|"streamable_http"; command:string; args:string[]; cwd:string; url:string; allowed_tools:ToolRule[] };
export type PublicServerConfig = ServerFields & { env_keys:string[]; header_keys:string[] };
export type ServerPatch = ServerFields & { env?:Record<string,string>; headers?:Record<string,string> };
export type PublicMcpConfig = {version:1;revision:number;servers:PublicServerConfig[]};
export type McpConfigPatch = {revision:number;servers:ServerPatch[]};
export type McpTestResult = {ok:boolean;latency_ms:number;tools:{name:string;description:string;inputSchema:Record<string,unknown>}[];error_code?:string};

