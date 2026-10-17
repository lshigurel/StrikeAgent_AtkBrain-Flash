# 外部 MCP 工具

应用后端作为 MCP 客户端，支持 stdio 和 Streamable HTTP。Pi 沿用现有
agent-tools 通道，向 recon / web-exploit 提供 mcp_list_tools 和 mcp_call_tool。
无需改模型配置，也无需给 Pi 直连 MCP 的权限。

## 运行位置

当前本机实例是 WSL 原生 systemd：后端、Pi、stdio 子进程均在 Ubuntu 内。
命令和工作目录填 Linux 绝对路径，例如 /home/shigure/apps/my-mcp/.venv/bin/python。
Windows 路径和 Windows 环境变量不会自动转成 Linux 路径。

若应用以后放入 Docker，stdio 进程就在容器内，需要把依赖装在容器内。
WSL 宿主机上的 stdio-only 服务应通过独立 Streamable HTTP 网关接入。
host 网络下 localhost 指宿主网络；bridge 网络下 localhost 指容器本身。
当前版本只允许 loopback 明文 HTTP，非 loopback 服务需要 HTTPS。
这次验收没有运行 Docker，不能据此推断某个容器网络组合已经兼容。

## 配置步骤

1. 打开设置页的“外部 MCP 服务”，添加 stdio 或 HTTP 服务。
2. 保持禁用，填写连接信息并保存。
3. “测试已保存配置”执行初始化和工具发现；stdio 会启动配置的程序，
   但不会发送 tools/call。检查返回的名称、说明和 inputSchema。
4. 审查服务实现，填写工具白名单，选择角色和范围规则，最后启用并保存。
5. Agent 先 mcp_list_tools，随后按原始 schema 传 arguments 调用 mcp_call_tool。
   修改配置后重新发现。保存本身不连接服务。

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
  "allowed_tools": []
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
  "allowed_tools": []
}
```

认证放在请求头 JSON，例如 {"Authorization":"Bearer ..."}，不能写入 URL。
仅支持无认证或静态请求头，不支持 OAuth、旧版 SSE、Resources、Prompts。
普通 REST 工具 API 不能直接当 MCP，需要协议适配。
测试发现成功只代表协议连通，不代表第三方服务的所有工具都兼容。

## 白名单与目标范围

白名单是规则数组。只有 recon / web-exploit 可被授权：

```json
[
  {"name":"parse_text","roles":["recon"],"profile":"pure","target_pointers":[]},
  {"name":"fetch_url","roles":["recon","web-exploit"],"profile":"http_url","target_pointers":["/url"]}
]
```

pure 仅用于已审查的无外部 I/O 纯计算工具；它不提供进程沙箱。
http_url 的 target_pointers 是 RFC6901 JSON Pointer，必须列出所有目标 URL。
每个目标均执行现有项目 HTTP 范围检查；缺失或越界即拒绝。
嵌套目标可用 /request/url，数组中的固定位置可用 /targets/0/url。
不要授权任意命令、任意脚本、隐式目标、可变长度多目标或自行重定向到其他目标的工具。
应用无法约束第三方程序的内部网络行为，服务必须可信并落实同样的范围限制。
不要把未知服务列出的工具自动全部加入白名单。

每项目同一时间一个外部操作；不同项目互相隔离。连接/发现默认 10 秒，
调用默认 30 秒；另留连接关闭时间。停止项目会取消排队及执行中的调用，
清理最多等待 5 秒。不自动重试 tools/call。
外部远程服务收到取消后是否终止自身任务，仍由其实现决定。

## 密钥、错误与审计

配置位于 backend/data/mcp-servers.json，目录 0700、文件 0600。
GET 只返回 env_keys/header_keys。编辑时留空保留旧值，填写 JSON 替换整组，
勾选清空或提交 {} 删除整组。不要在命令参数、说明和 URL 中放密钥。
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

