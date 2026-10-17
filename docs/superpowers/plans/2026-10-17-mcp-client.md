# StrikeAgent 外部 MCP 客户端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 StrikeAgent 通过可配置的后端 MCP 客户端发现并受控调用外部工具，完成设置页到 Agent 的闭环。

**Architecture:** Python 后端连接 MCP，复用现有 agent-tools 通道向 Pi 暴露两个固定工具。每次操作使用独立连接上下文，项目角色、白名单、schema、目标范围和停止控制在后端统一执行。Pi 扩展与启动参数保持兼容。

**Tech Stack:** Python 3.12、FastAPI、Pydantic 2、mcp 2.3.0、jsonschema 4.25.1；React 18、TypeScript、Vite；后端 unittest、前端 Vitest。

**Spec:** `../specs/2026-10-17-mcp-client-design.md`（待评审草案；执行前读两份文档）。

## Global Constraints

- 支持 stdio、Streamable HTTP；不包含旧版 SSE、OAuth、Resources、Prompts、服务端主动 sampling/elicitation。
- SDK 固定 `mcp==2.3.0`，校验器固定 `jsonschema==4.25.1`；Python 3.12，Node 22，Pi 0.74.2。
- 每个项目最多 1 个外部工具调用在执行；不增加批量扫描入口。不自动重试 `tools/call`，避免重复副作用。
- 连接与发现超时 10 秒，调用超时 30 秒，停止后清理限时 5 秒。
- 返回文本按 UTF-8 字节截断至 65536，并附截断标识；参数和返回正文不持久化。
- 配置目录 0700，文件 0600；保存不连接；GET 不返回 env/header 明文；revision 冲突返回 409。
- 默认禁用，显式工具白名单；全局执行角色仅 recon、web-exploit；角色映射不能扩大权限。
- 只用本地无害假服务验收；不连接生产目标；评审前不改动运行服务、业务源码或依赖。
- 用户目标拓扑：WSL Docker 应用经 host 网络调用 WSL 本机的 Streamable HTTP MCP。stdio 仅能启动应用所在环境内的进程；WSL 本机 stdio MCP 的 HTTP 网关属于独立前置条件。

## Review Focus

- 深层嵌套 arguments 的 schema 必须完整保留并验证；Task 3 的 nested schema 测试覆盖。
- Agent 排队时停止、禁用服务或修改规则后不能继续发出调用；Task 3 的 revision/stop 竞态测试覆盖。
- 两个项目的角色、凭据、进程与取消互不干扰；Task 2 与 Task 3 的双项目隔离测试覆盖。
- SDK 错误或工具正文回显凭据、大型 Unicode 结果不能泄露或破坏输出；Task 2 的脱敏与字节边界测试覆盖。
- 编辑服务而未重新填写密钥时保留原值，清空时真正删除，未登录不能配置；Task 4/5 的 API/UI 测试覆盖。

---

## 文件与边界

新增 `backend/atkbrain/mcp_client/`：`config.py` 配置模型与原子存储；`transport.py` SDK 适配、结果与错误归一；`bridge.py` 项目策略/并发/取消；`api.py` 管理 API；`agent_tools.py` 固定工具定义与闭包。新增对应 `test_config.py`、`test_transport.py`、`test_bridge.py`、`test_api.py`、`test_agent_integration.py`，`fixtures/echo_server.py` 和 `test_helpers.py`。

修改 `backend/requirements.txt`、`backend/atkbrain/api/routes.py`、`agents/mcp_http.py`、`agents/session.py`、`main.py`。不把 MCP 客户端代码塞进现有大型 tools.py；agent-tools 注册处合并固定定义。

新增 `frontend/src/features/mcp/{McpSettingsPanel.tsx,api.ts,types.ts,McpSettingsPanel.test.tsx}`；修改 `pages/SettingsPage.tsx`、`i18n/messages.ts`、`package.json` 和 lockfile；新增 `vitest.config.ts`、`test/setup.ts`。新增 `docs/mcp-client.md`。

所有命令默认在**隔离工作树根目录**，`PY=.venv/bin/python` 指向新建 Python 3.12 测试环境；Node PATH 使用部署目录的 Node 22 运行时。执行前读取 using-git-worktrees 技能并记录当前 revision、前端类型错误与原有定向测试基线。配置目录通过测试临时目录注入，不能访问真实 backend/data。

### Task 1: 配置模型与脱敏存储

**Files:** Create `backend/atkbrain/mcp_client/__init__.py`, `config.py`, `test_config.py`。

**Interfaces:**
- `ToolRule`, `ServerConfig`, `ServerConfigPatch`, `McpConfig` 为 Pydantic 模型，字段严格遵循 Spec。
- `ConfigStore(path: Path)`；`load() -> McpConfig`；`save(patches: list[ServerConfigPatch], expected_revision: int) -> McpConfig`；`public_config() -> dict`；`get(server_id: str) -> ServerConfig`。
- `ConfigConflict` 表示 revision 冲突；`save` 原子替换完整服务列表；省略 secrets 保留，空对象清除。

- [ ] **Step 1: 写失败测试。** `TestConfig.test_atomic_roundtrip` 断言保存后 revision=1、目录 mode=0700、文件 mode=0600；`test_keep_and_clear_secrets` 断言省略保留、{} 清除且 GET 无值；`test_reject_invalid` 覆盖相对 command、重复 ID、远端 HTTP、非法 transport、http_url 缺少 target_pointers；`test_conflict` 断言旧 revision 抛 ConfigConflict，原文件不变；`test_failed_replace_preserves_file` 模拟 replace 失败后原 JSON 仍完整。
- [ ] **Step 2: 验证失败。** `cd backend && ../.venv/bin/python -m unittest atkbrain.mcp_client.test_config -v`；预期导入缺失而失败。
- [ ] **Step 3: 实现模型与 ConfigStore。** Pydantic forbid extra；校验配置版本；写入前完整验证；每个 store 的串行写锁配合 revision。文件损坏返回明确配置错误，不能静默覆盖。
- [ ] **Step 4: 同一命令验证全部通过。** 增加 `test_corrupt_file_not_overwritten`，确认损坏配置保持原状。
- [ ] **Step 5: 提交。** `git add backend/atkbrain/mcp_client && git commit -m 'feat: add MCP server configuration store'`。

### Task 2: SDK 连接、发现与结果归一

**Files:** Modify `backend/requirements.txt`；Create `mcp_client/transport.py`, `test_transport.py`, `fixtures/echo_server.py`, `test_helpers.py`（这些路径均相对 backend/atkbrain）。

**Interfaces:**
- `RemoteTool(name: str, description: str, input_schema: dict)`、`ToolReply(text: str, is_error: bool, code: str|None)` 数据类。
- `McpTransport.describe(server: ServerConfig) -> list[RemoteTool]`、`invoke(server: ServerConfig, name: str, arguments: dict) -> ToolReply` 为 async；invoke 在同一连接中 list_tools、JSON Schema 校验、call_tool。
- `normalize_result(result: object, secrets: list[str]) -> ToolReply`；错误码 `connect_failed|timeout|invalid_arguments|remote_error|protocol_error|cancelled`。取消应继续传播 CancelledError 供桥接收口。
- 测试助手 `make_server(**overrides) -> ServerConfig`；假服务用 `mcp.server.MCPServer` 提供 echo、nested_echo、error、slow，命令行选 stdio/http，本机随机端口，维护仅供测试使用的调用计数。

- [ ] **Step 1: 写失败测试。** IsolatedAsyncioTestCase 中测试两种 transport 的 describe 返回 nested_echo 原始嵌套 schema；echo 原样回显；schema 非法时远端调用计数=0；error -> is_error=true；slow -> timeout 且只调用一次；取消 stdio 后子进程在 5 秒内退出；取消项目 A 的客户端不影响 B。纯函数测试 structuredContent 转 JSON，image/audio/resource 仅摘要，远端返回含 secrets 的文本与异常脱敏，中文超长输出 UTF-8 可解码且正文不超过 65536 字节（截断标记另计）。
- [ ] **Step 2: 运行失败。** `cd backend && ../.venv/bin/python -m unittest atkbrain.mcp_client.test_transport -v`；预期 transport 模块缺失。
- [ ] **Step 3: 安装固定依赖并实现适配器。** 官方 SDK 2.3.0 的 `Client` 与 transport API 只封装于本文件；检查包内 2.3.0 文档后使用该版本的 stdio/HTTP 构造方式，不套用 1.x 示例。stdio shell=False、新建进程组、cwd 明确，只继承 HOME/PATH/LANG/TMPDIR 并覆盖 server.env；HTTP trust_env=False、无重定向、TLS 校验。使用同一拥有任务中的 async context 关闭连接；不注册 sampling/elicitation 回调。SDK 异常先脱敏，再生成稳定错误码。
- [ ] **Step 4: 同一命令通过，运行 `.venv/bin/python -m pip check` 无冲突。** 若指定版本与基线依赖冲突，记录具体冲突并在评审中调整版本；不能偷偷升级生产环境。
- [ ] **Step 5: 提交。** `git add backend/requirements.txt backend/atkbrain/mcp_client && git commit -m 'feat: add MCP transport adapters'`。

### Task 3: 项目策略、固定工具与停止控制

**Files:** Create `mcp_client/bridge.py`, `agent_tools.py`, `test_bridge.py`；Modify `agents/mcp_http.py`（统一 REST/MCP 调用分派、定义合并）、`agents/session.py`（停止取消）、`main.py`（shutdown 清理）。

**Interfaces:**
- `McpBridge(store: ConfigStore, transport: McpTransport, is_running: Callable[[str],bool])`。
- async `list_tools(ctx: AgentContext, role: str, server_id: str|None=None) -> dict`；`call_tool(ctx: AgentContext, role: str, server_id: str, tool_name: str, arguments: dict) -> dict`；`cancel_project(project_id: str) -> None`；`close() -> None`。
- `external_tool_defs() -> list[dict]` 提供 mcp_list_tools、mcp_call_tool（arguments 为 additionalProperties=true 的 object）；async `dispatch_external(ctx: AgentContext, role: str, name: str, args: dict, bridge: McpBridge) -> dict`。
- REST 与 MCP handler 均从每次 request 的 x-atkbrain-role 提取角色传入；不在 ctx 上存 role。现有原生工具 map 不变；只在新增两个工具匹配时转入 dispatch_external。

- [ ] **Step 1: 写失败测试。** `test_role_and_whitelist_deny_before_connect` 对 lead、unknown、空 role、禁用服务、白名单外工具断言 transport 调用次数=0；`test_nested_schema` 合法嵌套对象成功、非法对象拒绝；`test_all_target_pointers_checked` 两个 URL 有一个越界则不调用，缺失字段亦拒绝；`test_project_serialization` 并发进入数<=1；`test_stop_while_waiting` 停止后第二次调用次数=0；`test_revision_changed_while_waiting` 更新规则后第二次拒绝；`test_project_isolation` A 停止不取消 B；`test_audit_metadata_only` 事件无参数、正文和密钥。
- [ ] **Step 2: `cd backend && ../.venv/bin/python -m unittest atkbrain.mcp_client.test_bridge -v`，确认缺少桥接而失败。** 测试使用 AsyncMock transport 和真实 ConfigStore 临时文件，构造 ctx.scope/guard，不发网络。
- [ ] **Step 3: 实现桥接和固定工具分派。** URL JSON Pointer 按 RFC6901 解码并调用 ctx._http_blocked；空或不确定目标拒绝。project lock 获得后再次检查 running、revision、规则；每个项目保存活跃 task 集供 cancel_project。权限错误统一成 is_error=true、code=denied。集成现有 scheduler 状态和 events.emit，不写参数或正文；保持现有其他工具行为。
- [ ] **Step 4: 运行 Task 1–3 测试全部通过。** 添加 `test_rest_and_mcp_have_same_denial`，两入口传相同 role 必须得到同样拒绝，防止现有 MCP _dispatch 绕过检查。
- [ ] **Step 5: 提交。** `git add backend/atkbrain && git commit -m 'feat: expose policy-controlled MCP tools to project agents'`。

### Task 4: 受鉴权的管理 API

**Files:** Create `mcp_client/api.py`, `test_api.py`；Modify `api/routes.py`（挂载新 router）。

**Interfaces:** `make_router(store: ConfigStore, transport: McpTransport) -> APIRouter`；API 路径、请求与响应遵循 Spec。PUT request `{revision:int, servers:list[ServerConfigPatch]}`；GET/PUT response `{version:1, revision:int, servers:list[PublicServerConfig]}`；test response `{ok:bool, latency_ms:int, tools:list[RemoteTool], error_code?:str}`，input_schema 在 JSON 中统一输出 `inputSchema`。

- [ ] **Step 1: 写失败测试。** 通过测试 app 的真实鉴权中间件和临时 DB 验证未登录 GET/PUT/test ->401，待改密 session ->403；GET 无明文；PUT省略密钥保留、{}清除；冲突->409；非法配置->422；保存未连接；管理员 test disabled 服务仅发现、call_tool次数=0；协议异常响应无凭据。测试 token/session 只属于临时数据库。
- [ ] **Step 2: `cd backend && ../.venv/bin/python -m unittest atkbrain.mcp_client.test_api -v`，确认新接口缺失而失败。**
- [ ] **Step 3: 实现 router。** 复用现有入口和登录中间件，不给 /settings/mcp 增加 loopback 豁免；错误响应只输出稳定错误码。配置写接口不接受 Agent 传来的工具执行请求。
- [ ] **Step 4: 同一命令全部通过，运行现有 `atkbrain.auth.test_auth` 与 `atkbrain.auth.test_entry` 确认鉴权无回归。**
- [ ] **Step 5: 提交。** `git add backend/atkbrain && git commit -m 'feat: add authenticated MCP configuration API'`。

### Task 5: 设置页 MCP 管理面板

**Files:** 新增/修改前述 frontend 文件；Vitest 2.1.9、@testing-library/react 16.3.0、@testing-library/user-event 14.6.1、jsdom 26.1.0、@testing-library/jest-dom 6.6.3 固定为 devDependencies；测试 config 指定 jsdom 与 setup 文件。

**Interfaces:**
- `McpSettingsPanel(): JSX.Element`，嵌入 SettingsPage 一次。
- `getMcpConfig(): Promise<PublicMcpConfig>`、`saveMcpConfig(input: McpConfigPatch): Promise<PublicMcpConfig>`、`testMcpServer(id: string): Promise<McpTestResult>`。
- frontend/src/api.ts 将已有 `req<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T>` 改为导出；MCP api 使用它保证 appBase、凭据、API token、错误处理与现有请求一致，不另建请求封装。

- [ ] **Step 1: 写失败测试并补充测试脚本。** 面板测试 mock MCP api：初始显示 disabled；能添加两种 transport 并保存；空密钥不出现在 patch，清空按钮生成 {}；显示 revision 冲突并保留未保存表单；测试连接仅调用 testMcpServer；成功显示工具 schema，失败显示错误码；不把 header/env 值放进列表。api 单测断言经过现有 req/appBase。安装上述测试依赖后运行 `cd frontend && npm run test -- --run`，确认面板缺失失败。
- [ ] **Step 2: 实现 types/api/面板与中英文文案。** 复用原样式，JSON 编辑器校验 args/env/headers/allowed_tools 的形状，保存时保留草稿；测试按钮明确显示会启动 stdio 进程；不增加前端 tools/call 按钮。
- [ ] **Step 3: 相同测试通过。** 执行 `npx vite build` 成功；`npx tsc -b --pretty false` 与基线比较，新文件零诊断、旧诊断不增加；保留完整日志，不声明整体 tsc 通过。
- [ ] **Step 4: 提交。** `git add frontend && git commit -m 'feat: add MCP settings panel'`。

### Task 6: 真实本地闭环、运维说明与交付

**Files:** Create `backend/atkbrain/mcp_client/test_agent_integration.py`, `pi/tests/mcp-extension-smoke.mjs`, `deploy/compose.mcp-test.yaml`, `docs/mcp-client.md`；复用 Task 2 fixtures。

**Interfaces:** 无新增产品接口；文档给出两种传输完整示例、绝对 Linux 路径说明、stdio PATH/env、项目工具授权与角色、超时、错误码、保存后重新发现，以及停机备份/回滚命令。

- [ ] **Step 1: 写闭环测试。** 临时启动独立端口后端、临时配置和本地假 MCP 服务；通过实际 agent-tools REST 获取两个工具。Node harness 使用 Pi 安装附带的 jiti 加载未修改的 `pi/extensions/atkbrain-tools.ts`，以仅实现 on/registerTool 的 fake ExtensionAPI 捕获注册定义；调用捕获的 execute 回调，实际经过 HTTP 后端和本地 MCP echo 服务。参数 `PI_PACKAGE_ROOT` 是 Pi node_modules 的绝对路径，jiti alias 显式解析其中的 @earendil-works/pi-coding-agent 与 typebox；ATKBRAIN_TOOLS_BASE/PROJECT_ID/PI_ROLE 指向测试实例。断言两个工具注册、echo 完整回显、HTTP/stdio 两条路径成功、REST/MCP 同等拒绝、停止后无子进程。该测试不需要模型 Key，不声称覆盖 Pi RPC 或模型选工具能力。
- [ ] **Step 2: 先写 Python 测试调用尚不存在的 harness，运行 `cd backend && ../.venv/bin/python -m unittest atkbrain.mcp_client.test_agent_integration -v`，确认 harness 缺失失败；再实现 harness 和必要接线使其通过，不在测试里绕过权限。**
- [ ] **Step 3: 完成文档和接线，运行全套定向验证。** `cd backend && ../.venv/bin/python -m unittest discover -s atkbrain/mcp_client -t . -p 'test_*.py' -v`；现有 auth 两个测试模块；frontend 定向测试和 Vite 构建；pip check。断言所有测试服务只监听 loopback，临时配置已清理，运行中的 2333/2334 未变化。
- [ ] **Step 3a: 验证用户的容器/WSL边界。** `deploy/compose.mcp-test.yaml` 使用独立 compose 项目名、network_mode: host、隔离临时数据、非 2333/2334 测试端口；WSL 本机 fixture 启动 Streamable HTTP echo，测试容器中的 McpTransport.describe/invoke 通过 127.0.0.1 成功。stdio 测试在容器内执行 fixture 并核对进程归属；测试不依赖 WSL 安装的工具路径挂载。文档明确 localhost 在 host/bridge 两种网络下的不同含义，现有 REST 服务需适配，stdio-only 宿主服务需单独网关。不得连接未知 MCP 或真实业务工具，结束清理测试容器，不改变当前部署方式。
- [ ] **Step 4: 提交并交付评审。** `git add backend/atkbrain/mcp_client pi/tests deploy/compose.mcp-test.yaml docs/mcp-client.md && git commit -m 'test: verify MCP integration and document operation'`。列明实际通过项、存量 tsc 错误与未验证真实外部服务。不把 echo 成功表述成 HexStrike 全工具兼容或模型决策能力验证。
- [ ] **Step 5: 用户批准部署并确认运行方式后执行。** 当前实际运行是原生 systemd，不可直接声称已经 Docker 部署。保持原生时先确认无运行项目，备份 backend/data/服务单元/依赖 freeze，合入并安装已验证依赖、构建前端、重启服务、检查健康与 Windows HTTPS。若用户选择迁移 Docker，迁移本身另列清单并验证镜像构建、数据挂载/所有权、容器访问本机 MCP、停止旧服务释放端口，再启动新容器；不能直接套用 systemd 发布步骤。新 MCP 默认 disabled；回滚恢复对应旧 revision、环境与数据。禁止改变宿主机现有工具安装或挂载 Docker socket。

## 自审记录

Spec 的配置、两传输、角色/范围检查、取消隔离、密钥、前端管理与验收分别由 Task 1–6 承担；Review Focus 五项均落到测试。固定工具接口没有遗漏动态 schema 校验；REST/MCP 双入口统一检查；没有引入全局 ctx.role；没有假设 MCP 1.x 与 2.x API 可混用。首个真实 MCP 服务和其安全白名单仍由用户评审时确定，但通用模块以本地假服务独立验收。

当前只完成规划，不开始上述任务；执行方式需用户选择。
