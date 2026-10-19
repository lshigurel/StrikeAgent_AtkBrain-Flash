# StrikeAgent 可追溯证据链设计

状态：待用户审阅。日期：2026-10-19。

## 1. 需求理解与范围

用户已在架构评审后选定“把可追溯的证据链加上”，并要求使用 Superpowers 审查与实施流程。

目标：任何新产生的已验证发现，都能沿“发现 → 验证结论 → 本次工具观测 → 实际调用”回溯；占位文字、请求中的命令、模型自行填写的通过标志不能替代验证。已有数据可查看，不能被伪造为具有新证据链。

遵守本会话授权测试约束：不额外探测目标、不自动重放旧 PoC、不增加扫描并发、不读取服务器敏感文件、不保存真实用户数据。功能测试只用合成数据、临时数据库和本地模拟传输。

本期范围：工具采集、证据关联、首次/二次验证门槛、图与自动化消费者、详情展示和报告引用。完整假设图、跨任务反证传播、调度器优化、模型路由不在本期。

基线：本机 Ubuntu WSL 项目 `/home/shigure/apps/StrikeAgent_AtkBrain-Flash`，HEAD `bba380911530f5c6d77c21f1fc1b287aa7e6c5e3`。已有 scope、proxy、projects、部署脚本等未提交修改必须保留；实施与测试不启动或重启生产服务。

## 2. 审查依据

以下均来自当前源码，不能只修其中一处：

1. `backend/atkbrain/graph/verify.py`：非空 evidence、PoC、canary 等字段即可使首次验证通过。
2. `backend/atkbrain/graph/finding_claim.py`：在标题/说明/请求/证据合并文本中匹配 whoami 等关键词，无法区分请求与执行响应。
3. `backend/atkbrain/graph/store.py`：`accept_secondary_review()` 可凭二次验证布尔值覆盖 pending；合并上报还会保留旧的 verified 状态。
4. `backend/atkbrain/db.py`：启动迁移会把 secondary_verified=1 的 pending/flaky 发现升为 verified，可能重新打开绕过。
5. `backend/atkbrain/events.py`：广播事件使用字符串 ID，而入库 events 使用自增 ID，当前 emit() 不返回该数据库 ID；不能把广播 ID 假装成可查的持久引用。
6. `backend/atkbrain/agents/tools.py`：HTTP 结果事件主要是状态码；命令事件只含预览，缺少统一调用 ID。节点自动生成 finding、report_shell 和自动识别 id 回显也会改变图与目标状态。
7. `backend/atkbrain/agents/mcp_http.py`：内置工具和外部 MCP 路径不同；角色字符串来自请求头，单凭它不能证明独立复核身份。
8. UI、报告、记忆和监督逻辑存在“缺少状态按 verified 处理”或根据图节点直接视为已控资产的路径，必须一并审查。

上轮已经用纯内存样例复现第 1、2 项；其余是静态代码观察，不宣称已在运行中的服务复现。

## 3. 方案选择

采用：保留现有 SQLite、图与事件总线，增加小型追加式证据存储与统一验证服务。

替代方案 A：只给 FindingIn 加 source_event_id。改动小，但现有事件不保存足够内容，且仍有二次验证与图节点绕过，不采用。

替代方案 B：重建完整事件溯源与假设图。表达力强，但改动范围远超本次需求，不采用。

证据链采用独立 UUID，不依赖 events 表 ID，避免重构整个事件总线。它提供应用级来源追踪和内容校验，不声称能抵抗有数据库或宿主机写权限者的篡改。

## 4. 数据与职责

新增 `backend/atkbrain/evidence/`，分为 model、capture、store、verify 四个职责。数据库仍由现有 Database 管理，新增表与必要的事务方法，不更换数据库或引入服务依赖。

### 4.1 ToolObservation：后端采集的观测

字段：`id`、`project_id`、`run_id`、`invocation_id`、`session_id`、`role`、`review_job_id`、`tool_name`、`source_kind`、`started_at`、`completed_at`、`outcome`、`request_summary`、`response_metadata`、`retained_excerpt`、`retained_sha256`、`redaction_version`、`truncated`、`capture_error`。

- UUID、项目/运行/会话/角色/时间与执行结果由后端填写；工具参数不得覆盖。
- source_kind 区分 HTTP 响应、命令 stdout/stderr、外部 MCP 结果、人工导入。通用命令输出不被自动当成远程主机执行证明。
- outcome 区分 success、error、blocked、cancelled。错误和拦截可以追踪，但不能证明漏洞成立。
- 每次调用一条终态记录。取消、超时也保留元数据；既不写成阴性漏洞结论，也不触发自动重试。
- 应用内只追加，不提供修改内容的接口。删除项目时按现有项目生命周期删除证据及引用，不能留下孤立记录。

### 4.2 EvidenceClaim：人或模型提出的解释

字段：`id`、`project_id`、`finding_id` 或 `node_key`、`observation_ids`、`claim_kind`、`summary`、`created_at`、`actor_session_id`。

claim_kind 为 observed、hypothesis、validation 或 contradiction。摘要是解释，不是原始事实。引用必须真实存在且属于同一项目；允许同项目旧运行的观测用于说明，不能用于冒充本轮独立复核。

### 4.3 VerificationRecord：验证决策

字段：`id`、`project_id`、`finding_id`、`stage`、`decision`、`reason_code`、`observation_ids`、`assertion_kind`、`assertion_detail`、`validator_kind`、`validator_session_id`、`review_job_id`、`created_at`、`supersedes_id`。

- stage：primary 或 secondary。
- decision：supported、disproved 或 inconclusive；blocked/error 属于观测状态，不等于 disproved。
- validator_kind：deterministic 或 designated_reviewer；人工导入材料可追踪，但不自动获得通过权限。
- 决策追加记录；后续结论通过 supersedes_id 指向前一条。合并发现时保留证据历史，不能覆盖首次证据或把不同入口混成同一证明。
- 数据库外键/服务校验共同保证引用存在与项目一致；找不到证据时明确失败，不静默通过。

## 5. 采集、最小化与隐私

调用前生成 invocation_id，调用后在运行时返回相同 ID 和 observation_id。前后事件也带这些 ID。凭后端来源关联，不能凭“最近一条工具结果”猜测。

不持久化完整 HTTP 正文、完整命令输出、上传文件、数据库结果或用户数据。默认保存请求方法、脱敏 URL、状态码/退出码、耗时、错误类型及证据捕获状态。

允许保留的响应证据限定为：系统生成的无害 canary、状态/长度等标量、明确允许的版本信息，以及通过受控字段提取器输出的非用户数据。正文不能通过通用 evidence 字段直接灌入观测表。

Authorization、Cookie、Set-Cookie、密码、token、AK/SK 等字段和运行时已知秘密在任何持久化前脱敏；未知业务结构或可能含真实用户数据时只保留元数据，状态为 evidence_unavailable。不得把“先全量存储、展示时打码”作为实现。

请求摘要最多 1024 字符、响应保留片段最多 2048 字符；截断明确标注。哈希只覆盖实际保留且已脱敏的规范化内容，不宣称是未保存原文的哈希。新路径的事件、工具关联信息和错误日志同样不得旁路写出原文。

本期收紧与证据链直接相关的现有 run_cmd/http_request 事件持久化，避免新证据已脱敏而相邻事件仍记录密钥。通用模型文本日志的全面敏感信息治理不在本期，已存在的数据也不自动重写。

## 6. 可信调用上下文

为每个 Pi 会话注册后端生成的短期调用凭据，绑定 project/run/session/role。请求上下文通过 ContextVar 或显式不可变参数传递，不能写进共享 AgentContext 的可变 role 字段，以免并行调用串线。

凭据只用于后端工具调用，不交给目标、不进入事件或报告。Pi 会话退出/取消时撤销，重启后旧凭据失效。原有登录/API 认证与 scope 守卫保持生效；该凭据是新增会话绑定，不替代它们。

REST 与 Streamable HTTP MCP 两种入口使用相同的调用上下文。模型在参数或 x-atkbrain-role 中自行声称 reviewer 不产生复核权限。旧客户端可以继续上报线索，但缺少可信会话绑定时不能写入通过决策。

复核作业开始时由服务端绑定 review_job_id、允许复核的 finding_ids 和开始时间；自动复核批次同样获得服务端登记的范围。引用证据必须来自复核开始之后的独立调用，且不是首次验证所用的 invocation_id。新会话和新调用不保证不同模型或完全独立判断，界面不作这种夸大声明。

这不是宿主机沙箱：具有宿主机任意读取或数据库修改权限的对手不在本次应用级来源证明范围内。

## 7. 验真规则与防绕过

新增发现的 verification_status 默认 pending。旧 evidence、poc_curl、proof_detail 等保留用于说明与复现，但非空不再自动通过。调用方传入 verified 或 secondary_verified 仅是请求，最终状态由服务端验证记录计算。

第一期提供两类通过路径：

1. 后端支持的确定性断言，基于成功的可信工具观测执行。断言配置必须受约束，不能接受任意 Python、JS、正则代码或文件路径。系统 canary 必须由后端生成并在调用前绑定，完整期望值不得原样出现在请求中；仅反射请求不算执行证明。仅支持的输出类型能由此直接得到 supported。
2. 指定复核员对同一目标/入口的工具观测作出有理由的判断。判断必须引用可查询观测及可保留证据，不得凭自由文本独立创建成功观测。对非确定性漏洞仍是可审计的评估，不声称后端通用匹配器能证明所有漏洞。

没有受支持断言或没有足够可保留观测时维持 pending/inconclusive，并明确下一步缺什么；不通过收集用户数据或扩大测试影响补证。

RCE 判定只读取关联响应证据/允许的远程观测，不能扫描标题、PoC 请求或描述里的 whoami。远程定位不明确的 run_cmd stdout、静态 uid= 字符串、HTTP 200、版本命中均不能自动证明执行。命令退出码 0 只说明该命令正常结束。

独立复核通过必须有新的 supported secondary 记录；secondary_verified=true、40 字理由、旧布尔标志和被复用的旧调用都不能替代。仅评级不会提升验真状态。excluded/disproved 保留历史，补充新证据通过时必须有新决策记录。

统一门槛必须覆盖：report_finding、add_node 自动生成发现、report_shell、maybe_autoland_shell、合并发现、后台复核、图/API 序列化、报告与经验蒸馏。未经支持的 RCE 声明不得先点亮 GETSHELL、提前完成目标或产生已控能力边。自动识别可提出待核验 claim，不能绕过门槛。

本功能只改变“何时信任一项结论”，不新增 shell、提权、横向或敏感数据读取步骤，也不自动执行任何证明请求。

## 8. 旧数据与下游兼容

迁移只新增表/列，重复启动应幂等。新记录 provenance_version=1；旧记录标记 legacy_unlinked，不根据旧文本伪造观测 ID，也不批量重放目标请求。

旧记录原始状态和报告仍可读，并明确显示“历史记录，缺少可追溯证据”。原始字段不批量删除或改写，但本期统一 effective_verification_status：缺少可用支持记录时为 pending，不能继续作为新轮次已验证资产、自动收工或经验强化的依据。历史报告保留当时结论，同时显示来源缺口。

移除启动迁移中“secondary_verified=1 即升级 verified”的行为。合并记录不能因旧状态/旧二次标志跳过当前门槛。新 UI、报告和自动化不得把空状态默认当 verified。

API 返回 provenance_status、effective_verification_status、有效验证记录摘要和 observation_count。现有 verification_status 字段对新记录反映当前验证结果；legacy 原值另作展示说明。前端、监督器和记忆消费者统一使用有效状态。

## 9. 查询、界面与报告

- 在现有 finding 详情 API 和弹窗增加“证据链”：调用时间、工具来源、脱敏请求摘要、允许保留的响应证据、验证阶段和通过/未通过原因。
- 新增项目级只读 observation 查询工具与 API，均验证项目归属；引用别的项目 ID 返回不泄露详情的错误。观察工具只允许读取存储内容，不读任意磁盘路径、不发 HTTP。
- 节点可附 claim/observation 引用；假设、待核验和已验证的标记分开。点击来源可以打开同项目证据详情。
- Markdown/HTML 报告增加稳定证据 ID、时间及判断依据；没有捕获的信息明确写未保存，不拼造请求/响应。
- 英文/中文文案沿现有 i18n 添加；不另建仪表盘，不调整整体布局。

## 10. 失败处理与性能

证据写入失败时返回 evidence_capture_failed，同时保留原工具的运行结果；该结果不允许产生 supported。工具已执行的情况下不因记录失败自动重放。取消只写一次终态；重复上报用 invocation_id 去重。

验证记录、引用和发现有效状态在同一个数据库事务提交，不能出现已通过但缺引用的中间状态。广播只在事务提交后发送；广播丢失可从数据库重读。

观测按 project_id/run_id/invocation_id 建索引，详情分页，单次最多 50 条。不把全文写进每轮上下文，默认只给摘要与 ID，按需读取。

## 11. 预计改动位置

以下相对于上文项目根目录；实施计划会逐项给出签名和测试任务。

- 新增 evidence/model.py、capture.py、store.py、verify.py 和对应测试。
- db.py：追加迁移、索引和原子事务支持。
- agents/context.py、mcp_http.py、pi_runtime.py、session.py；Pi 扩展：会话绑定和调用关联。
- agents/tools.py 与 mcp_client/bridge.py：本地工具/外部 MCP 采集，发现与 shell 入口接统一门槛。
- graph/model.py、store.py、verify.py、finding_claim.py：关联字段、有效状态和防绕过。
- review/jobs.py、agents/prompts.py：复核上下文、观测引用和工具说明。
- engine/supervise.py、相关图/目标完成消费者、memory/evolve.py：使用有效状态。
- api/routes.py、报告生成模块、frontend/types.ts、FindingReportModal、节点详情与 i18n：只读展示和导出。

不改已存在的 scope/proxy 授权策略，不混入部署或其他未提交修改。涉及已有大文件的变更仅作接线，主要逻辑放入新模块。

## 12. 必须通过的验收用例

1. 占位 evidence、仅 PoC、仅 proof_url、直接传 verified 均不能产生 supported。
2. 请求中有 whoami/uid=/canary 而响应无证明，不能认定 RCE；完整反射请求也不能认定。
3. HTTP 成功响应、受控非用户 canary 和支持断言可组成真实来源链；泛化漏洞由有范围的复核决策判断。
4. 不存在、跨项目、失败/拦截观测不能作为通过证据；同项目跨运行可引用但不冒充新复核。
5. 旧 secondary_verified、单独评级、复用首次 invocation、伪造角色头不能提升状态。
6. add_node 自动发现、shell 上报与自动回显路径不能提前形成已验证资产或使目标完成。
7. 两个并行角色的 invocation/session/role 不串线；重复调用、取消与超时只落一次终态。
8. 证据写入失败不会通过、不会重放目标；状态和引用原子提交，事件可重读。
9. 秘密字段、真实用户正文不持久化；未知结构 metadata-only；截断有标记；哈希可从保留内容重算。
10. 迁移执行两次结果一致；legacy 可读但不冒充新证明；不删除原数据，不自动连目标。
11. 详情与报告显示来源、阶段和缺口；跨项目查询被拒；前端没有原始 HTML 执行或缺省 verified。
12. 现有相关后端/前端测试通过；新增验收先观察失败、再实现通过。测试只用临时库和模拟服务。

## 13. 审阅与后续

本文为可审阅设计，尚未实施产品代码。下一步在用户批准书面设计后，依 Superpowers writing-plans 生成实施计划并交付审阅；计划审阅通过后进入隔离实现、测试和代码审查。

建议后续采用本会话原生执行：我逐项实施并验证，完成后按 Superpowers 审查流程复核；用户若希望逐任务独立代理实现/审查，可在计划阶段选择。
