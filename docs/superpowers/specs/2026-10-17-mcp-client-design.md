# StrikeAgent 外部 MCP 接入设计草案

状态：待用户评审；本文件和实施计划不构成执行或上线批准。

## 部署边界补充（用户最新说明）

用户期望应用位于 WSL Docker，安全工具和 MCP 位于 WSL 本机。2026-10-17 实际只读核验显示：当前 StrikeAgent 2333/2334 仍由原生 systemd 运行；Docker 中是 Artex 和 PostgreSQL。本设计按用户说明兼容后续容器部署，但本轮不迁移服务，也不把 Artex 当作 StrikeAgent。

目标链路为：容器内 StrikeAgent/Pi -> 后端 MCP 客户端 -> Streamable HTTP -> WSL 本机 MCP -> WSL 本机工具。项目 compose.yaml 默认 network_mode: host，沿用这一网络模式时 MCP 可只监听 WSL 的 127.0.0.1，容器使用其实际端口和路径访问。禁止把宿主机目录挂载或 Docker socket 当作执行宿主机工具的手段。

stdio 支持仅指启动“应用所在环境内”的 MCP 进程：应用在容器时，stdio 子进程也在容器中，不能直接执行 WSL 本机安装的工具。WSL 本机若只有 stdio MCP，需由 WSL 常驻的 stdio-to-Streamable-HTTP 网关持有该进程，应用连接网关；该网关部署是独立前置条件，不暗示本计划已实现或已部署。已有 REST 工具服务不能直接当成 MCP 服务，必须验证 initialize/tools/list 协议响应。

不默认切换为 Docker bridge。若未来选择 bridge，localhost 将指向容器；需单独设计 host-gateway 地址、WSL 监听地址与访问规则，同时调整本计划仅 loopback 允许明文 HTTP 的基础设施校验，不能简单替换地址后声称兼容。

## 目的与已知条件

在 `/home/shigure/apps/StrikeAgent_AtkBrain-Flash` 的已部署版本（4072417）上增加外部 MCP 客户端，使 Agent 能发现并调用管理员配置的 MCP 工具。用户已要求二开与实施规划，尚未指定首个外部服务；因此采用通用接入方案，以本机无害 echo 服务验收，不能预设某个 HexStrike 地址已经兼容。

已有 Pi 扩展从后端 `/api/projects/{pid}/agent-tools` 获取工具；`pi_runtime.py` 通过 `--no-extensions -e atkbrain-tools.ts` 显式加载扩展。后端已有 `/projects/{pid}/mcp` 是向外提供本项目工具的服务端，不是外部 MCP 客户端。

## 方案比较与选择

1. **推荐：后端桥接。** Python 后端管理 MCP 连接，现有 Pi 扩展调用固定的 `mcp_list_tools`、`mcp_call_tool`。便于保留项目上下文、停止控制与范围检查；首版可不修改 Pi 加载流程。
2. Pi 内直接增加 MCP 扩展：更直接，但要同时维护 TypeScript 依赖、扩展加载与后端权限策略，容易形成两套执行通道。
3. 通过 CLI 网关调用：适合临时单服务验证，难以统一配置、错误与连接生命周期，不作为产品方案。

本草案选择 1；这是一项新的接入子系统。首版以可配置、可测试的完整闭环为范围。

## 首版范围与明确限制

- 支持 stdio、Streamable HTTP；不包含旧版 SSE、OAuth、Resources、Prompts、服务端主动 sampling/elicitation。
- SDK 固定 `mcp==2.3.0`，校验器固定 `jsonschema==4.25.1`；Python 3.12，Node 22，Pi 0.74.2。依赖兼容性在隔离环境验证；不混用 MCP SDK 1.x 的 ClientSession 接口。
- 默认禁用所有服务；服务启用后仍需显式工具白名单。只支持当前单管理员模型，不引入多租户。
- 每个项目最多 1 个外部工具调用在执行；不增加批量扫描入口。不自动重试 `tools/call`，避免重复副作用。
- 连接与发现超时 10 秒，调用超时 30 秒，停止后清理限时 5 秒；超时后连接失效，下一次显式调用重新建立。
- 每次发现/调用拥有自己的 SDK 客户端上下文。调用时在同一上下文重新发现并验证 schema，再调用；首版不共享长期连接，也不缓存跨项目会话。
- 仅 `recon`、`web-exploit` 角色允许使用配置授权的工具。`lead`、复核、报告、无工具角色及未知角色不可调用；现有角色列表见 `agents/prompts.py`，执行前确认实际字符串与此约定相符并只做必要映射。

## 配置与 API

全局配置保存在 `backend/data/mcp-servers.json`，目录 0700，文件 0600，同目录临时文件原子替换。格式：`{version:1, revision:int, servers:[ServerConfig]}`。不写入 Git、不复用模型 JSON。

ServerConfig：`id` 匹配 `[a-z][a-z0-9_-]{0,31}`；`enabled` 默认 false；`transport` 为 `stdio|streamable_http`；`allowed_tools: list[ToolRule]`。stdio 使用绝对 Linux `command` 路径、`args: list[str]`、绝对 `cwd`、`env: dict[str,str]`，禁止 shell 拼接；不自动运行 npm/npx 下载依赖。HTTP 使用 `url`、`headers`，远端必须 HTTPS；HTTP 仅允许字面量 localhost/127.0.0.1/[::1]，关闭重定向，TLS 校验保持开启。配置中的服务地址是基础设施连接地址，与测试目标范围分别校验。

ToolRule：`name:str`、`roles:list[str]`、`profile:pure|http_url`、`target_pointers:list[str]`。规则只能收窄全局角色限制，不能扩大。`pure` 仅供管理员审阅过的无网络、无文件或命令执行能力的工具；其声明不是沙箱保证。`http_url` 必须列出全部目标字段的 JSON Pointer，缺失或非字符串目标拒绝；复用 `AgentContext._http_blocked(url)` 校验，每个目标均通过才调用。工具可接受的其他参数仍由完整 JSON Schema 验证。通用命令执行、批量目标、上传、持久化、提权、横向移动等工具不进入首版白名单；不能仅相信 MCP readOnlyHint。

配置 GET 不返回 env/header 明文，只返回 env_keys/header_keys。更新通过专用 `ServerConfigPatch`：省略 env/headers 保留，显式 `{}` 清空，传入对象替换。更新必须携带 revision，冲突 HTTP 409。普通日志、事件、Agent 目录均不包含配置密钥。

API 全部沿用现有入口与鉴权：
- GET `/api/settings/mcp` -> 脱敏配置与 revision。
- PUT `/api/settings/mcp` -> 提交完整非密钥字段与上述密钥 patch，成功 revision +1；不发起连接。
- POST `/api/settings/mcp/{id}/test` -> 仅 initialize + tools/list；即使 disabled 也允许管理员显式测试，不调用业务工具。返回工具名与完整 inputSchema、耗时；错误脱敏。
- 不提供绕过项目角色和范围限制的通用管理 tools/call 接口。

## Agent 工具与生命周期

新增 `mcp_list_tools(server_id?:str)`：只返回已启用且存在授权规则的服务、工具名、描述和完整 inputSchema，不暴露地址、启动参数或凭据。

新增 `mcp_call_tool(server_id:str, tool_name:str, arguments:dict)`：检查当前项目在运行、角色、启用状态、白名单、schema 和目标范围，获取项目单并发闸后再次检查运行状态和配置 revision，然后执行。排队期间配置改变则拒绝，要求重新发现。现有 Pi 扩展支持 arguments 对象；远端复杂 schema 放在发现结果中，后端完整验证，不依赖扩展当前的简化 schema 转换。

REST agent-tools 与现有 MCP tools/call 必须走同一个外部工具调度检查，避免只在其中一个入口检查。将角色作为每次调用的显式参数传入桥接，禁止放进共享 AgentContext 后再覆盖。收到未授权角色时不连接远端。

项目停止时取消该项目的排队与执行任务；stdio 进程组由其所有者关闭，不杀其他项目进程。应用 shutdown 关闭所有活跃客户端。使用 SDK 异步上下文并在同一拥有任务内退出，避免跨 task 关闭 anyio cancel scope。

返回给现有工具通道：`{content:[{type:'text',text:str}], is_error:bool}`。JSON structuredContent 转为 JSON 文本；image/audio/resource 仅输出类型摘要，不自动下载。文本按 UTF-8 字节截断至 65536，并附截断标识。MCP isError 与协议错误分别转成稳定错误码，不把远端结果自动当成漏洞证据或可信指令。

事件 `mcp.call` 仅包含 server_id、tool_name、role、状态、耗时、错误码。参数、远端结果正文、header/env、stdout/stderr 均不保存到事件或数据库。SDK 异常和凭据回显先脱敏，再限制输出大小；远端工具仍是受信任代码，首版不宣称可以阻止恶意服务自行外传数据。

## 设置页

新增 MCP 面板：服务列表、添加/编辑/删除、启停开关、传输配置、白名单规则、测试连接及工具 schema 查看。与现有中文/英文语言系统一致。密钥字段为空时保留，另设“清空”操作；保存不会启动进程。连接测试会明确提示 stdio 将启动本地进程。使用现有样式和请求封装，避免扩大 SettingsPage。

## 验收与上线

使用只提供 echo、nested_echo、error、slow 的本机假 MCP 服务，分别覆盖 stdio 与 Streamable HTTP；不访问任何真实业务目标。Node 测试 harness 使用 Pi 自带 jiti 加载现有扩展，以 fake ExtensionAPI 捕获注册的工具并调用 execute 回调；请求实际经过后端与本地 MCP，不需要模型 API Key。此验收覆盖扩展注册与工具执行通道，不覆盖完整 Pi RPC 会话或模型选工具。验证越权角色、未授权工具、范围外 URL、嵌套参数非法、停止及超时均不产生额外远端调用。

当前 `npm run build` 已存在类型错误；记录基线。新增功能不得新增 TypeScript 诊断，Vite 构建及定向前端测试必须通过，不把存量错误宣称为本功能已修复。

实施在 using-git-worktrees 创建的隔离工作树中进行；测试虚拟环境位于该工作树。另用 network_mode: host 的测试容器验证访问 WSL loopback 假 MCP，stdio 测试需明确进程在容器内；不能由容器外测试冒充。评审与测试通过后，根据确认的目标部署方式发布：保持原生部署则同步运行目录并重启 systemd；若改为 Docker，另行准备镜像与数据迁移，不能让两套服务争抢端口。新增 MCP 默认禁用，保留旧配置可回滚。

参考：本地 `agents/mcp_http.py`、`agents/pi_runtime.py`、`pi/extensions/atkbrain-tools.ts`；官方 SDK https://github.com/modelcontextprotocol/python-sdk ，PyPI https://pypi.org/project/mcp/ （2026-10-17 核验版本 2.3.0）。
