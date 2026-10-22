# 外部 MCP 工具

应用后端作为 MCP 客户端，支持 stdio、Streamable HTTP 和旧版 SSE。Pi 沿用现有
agent-tools 通道，向获授权的 lead（主控）、内置或自定义执行 Agent 提供 mcp_list_tools 和 mcp_call_tool。
无需改模型配置，也无需给 Pi 直连 MCP 的权限。

## 运行位置

当前本机实例是 WSL 原生 systemd：后端、Pi、stdio 子进程均在 Ubuntu 内。
命令可填写 WSL 中的程序名（例如 npx、uvx）或 Linux 绝对路径；参数单独添加。
程序名按后端进程的 PATH 查找；省略工作目录时使用后端运行用户的主目录。
Windows 路径和 Windows 环境变量不会自动转成 Linux 路径。

若应用以后放入 Docker，stdio 进程就在容器内，需要把依赖装在容器内。
WSL 宿主机上的 stdio-only 服务应通过独立 Streamable HTTP 网关接入。
host 网络下 localhost 指宿主网络；bridge 网络下 localhost 指容器本身。
HTTP、HTTPS 均可连接填写的 MCP 服务地址；HTTPS 保持证书校验。
这次验收没有运行 Docker，不能据此推断某个容器网络组合已经兼容。

## 配置步骤

1. 打开设置页的“外部 MCP 服务”，点击“添加 MCP 服务”或“编辑连接”。
2. 填写名称，选择本地命令（stdio）、HTTP 或 SSE。
3. stdio 填命令，逐行添加参数、环境变量；HTTP/SSE 填 URL，逐行添加请求头。
   可在“表单”和“JSON”之间切换。已保存的密钥不回显，值留空保留，
   删除对应行才会移除该键；其他未修改的键会保留。
   JSON 中省略 env/headers 会保留当前草稿；显式填写 {} 才清空对应组。
4. 在“允许使用的 Agent”中多选 lead（主控）、内置或自定义 Agent。选中的 Agent 可发现并调用
   该服务提供的全部工具，不需要工具白名单。不选任何 Agent 表示不授权任何 Agent。
5. 保存后可使用列表中的“测试已保存配置”执行初始化和工具发现；
   stdio 会启动配置的程序，但不会发送 tools/call。
6. 列表显示每个服务已授权的 Agent。再次编辑可调整授权；停用或删除的 Agent
   无法调用，即使历史配置中仍保留其 ID。新连接默认禁用、默认不授权任何 Agent，
   可在列表中启用。保存本身不连接服务。

stdio 字段示例（请将路径替换为实际安装位置）：

```json
{
  "id": "local-parser",
  "enabled": false,
  "transport": "stdio",
  "command": "/home/shigure/apps/my-mcp/.venv/bin/python",
  "args": ["/home/shigure/apps/my-mcp/server.py"],
  "cwd": "/home/shigure/apps/my-mcp",
  "url": "",
  "allowed_agents": ["recon", "custom-parser"]
}
```

仅继承 HOME、PATH、LANG、TMPDIR，可在环境变量 JSON 中覆盖或补充。
程序不经过 shell；shell 管道、重定向不会生效。环境变量填写一个字符串键值对象。

Streamable HTTP 示例：

```json
{
  "id": "local-http",
  "enabled": false,
  "transport": "streamable_http",
  "url": "http://127.0.0.1:8765/mcp",
  "command": "",
  "args": [],
  "cwd": "",
  "allowed_agents": ["recon", "web-exploit"]
}
```

认证放在请求头 JSON，例如 {"Authorization":"Bearer ..."}，不能写入 URL。
HTTP 和 SSE 均支持无认证或静态请求头；SSE 选择相应连接方式并填写服务的 /sse 地址。
不支持 OAuth、Resources、Prompts。
普通 REST 工具 API 不能直接当 MCP，需要协议适配。
测试发现成功只代表协议连通，不代表第三方服务的所有工具都兼容。

## Agent 授权与目标范围

`allowed_agents` 是服务级的 Agent ID 数组，支持 lead（主控）以及 Agent 管理页中的内置和自定义角色。
后端在发现和直接调用两处校验授权，不再根据工具名称或旧工具角色规则过滤。
未获授权的 Agent 不能发现该服务的工具，也不能绕过发现步骤直接调用。
空数组不授权任何 Agent。lead 默认没有授权，需手动勾选；评审、御主等其他保留角色不能使用外部 MCP。

旧配置首次读取时，从历史规则中的 roles 合并出服务级授权，避免默认扩大 Agent 范围；
没有历史规则的服务默认无授权。再次保存会写入 allowed_agents。历史 allowed_tools
不再作为白名单，也不通过设置接口返回；仅保留已有 http_url 规则的必要目标字段检查，
避免升级后丢失原有范围限制。只编辑连接的旧客户端会保留已保存的 Agent 授权。

调用参数中直接提供的 HTTP/HTTPS URL（包括嵌套对象与数组）执行项目 HTTP 范围检查；
越界或带凭证的 URL 被拒绝。第三方工具内部生成的地址或命令内嵌的目标不属于这一检查
的覆盖范围，MCP 服务自身仍需落实项目的范围限制。

每项目同一时间一个外部操作；不同项目互相隔离。连接/发现默认 10 秒，
调用默认 30 秒；另留连接关闭时间。停止项目会取消排队及执行中的调用，
清理最多等待 5 秒。不自动重试 tools/call。
外部远程服务收到取消后是否终止自身任务，仍由其实现决定。

## 密钥、错误与审计

配置位于 backend/data/mcp-servers.json，目录 0700、文件 0600。
GET 只返回 env_keys/header_keys。编辑时留空保留旧值，填写 JSON 替换整组，
连接编辑器按键更新，删除一行只删除对应键；旧 API 仍可提交 {} 删除整组。不要在命令参数、说明和 URL 中放密钥。
两次编辑使用 revision 乐观锁；冲突保留草稿，复制后重新加载并合并。

管理 API 受现有登录保护，路径均相对随机入口的 /api：

- GET /settings/mcp
- PUT /settings/mcp，正文 {"revision":0,"servers":[...]}
- POST /settings/mcp/{server_id}/test，只发现工具

稳定错误码包括 denied、connect_failed、timeout、invalid_arguments、remote_error、
protocol_error、catalog_too_large；管理 API 的 revision 冲突为 HTTP 409。
调用结果仅返回文本和结构化内容，二进制/资源只给类型摘要；
文本正文限制 65536 UTF-8 字节，超限附 [truncated]。
配置的密钥值会被脱敏；任意未配置的业务敏感内容无法自动识别。
事件只记录项目、服务、工具、角色、状态、错误码、耗时，不记录参数或返回正文。

## 验证

仅使用本地无害 echo fixture，无模型 Key，不访问业务目标：

```bash
export PI_PACKAGE_ROOT=/absolute/path/to/pi/node_modules
export PATH=/absolute/path/to/node/bin:$PATH
cd backend
../.venv/bin/python -m unittest discover -s atkbrain/mcp_client -t . -p 'test_*.py' -v
../.venv/bin/python -m unittest atkbrain.auth.test_auth atkbrain.auth.test_entry
cd ../frontend
npm ci
npm test
npx vite build
```

Pi smoke harness 加载已有 TS 扩展、捕获注册工具并执行其回调，
经真实 HTTP 后端到 stdio/HTTP fixture；没有验证 Pi RPC 或模型自动选工具能力。
未设置 PI_PACKAGE_ROOT 时该集成测试显式跳过。
原项目 tsc 有存量错误，新增文件不得增加诊断；Vite 构建单独验证。

## 原生实例发布与回滚

先确认没有运行项目。停止 backend/front 服务后，备份 backend/data、.env、
systemd 单元、旧 Git revision、旧 Python 环境的 pip freeze 及 frontend/dist。
备份目录应在仓库外，权限 0700，不提交凭据或数据。
在新环境安装 backend/requirements.txt 并 pip check，构建前端后，
切换服务到新代码及对应环境，再重启并检查健康、HTTPS 和管理接口。
新 MCP 配置默认空且禁用，不自动启用任何本机工具。

回滚时停止服务，恢复备份的代码 revision、Python 环境与前端 dist，
再启动；仅在明确需要且无新业务数据时恢复数据库备份。
切勿以旧数据库覆盖更新后的真实项目数据。本功能不迁移数据库结构。

