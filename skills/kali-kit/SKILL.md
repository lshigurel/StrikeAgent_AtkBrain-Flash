---
name: kali-kit
description: >
  This machine's Kali pentest tools: absolute binary paths, pinned wordlists,
  copy-paste commands (nmap, ffuf, hydra, ssh, sshpass, socat, sqlmap, JSFinder,
  bypass-403, nxc, impacket, binutils). Call only after you already decided you
  need that scanner or wordlist for an unknown surface. Do not call to start a
  CTF puzzle — encoding, crypto, protocol, or a hinted path is local python3 /
  openssl / http_request, not this skill. Never which / ls wordlists.
  Shared by CTF and red team. Not recon policy — that is recon-fanout /
  recon-spiral.
---

# 本机工具纪律
- Pi 用内置 `read` 加载本文件；之后作业只用扩展工具 `run_cmd` / `http_request`，不要用内置 bash。
- 下列路径已存在。禁止 `which` / `command -v` / `type` 探工具；禁止 `ls /usr/share/wordlists`、ls seclists、猜 MCP 名。
- 未列出的工具当不存在。不要编造系统包名去 which。
- 命令一律 `run_cmd`；HTTP 优先 `http_request`。
- CTF 与红队一律禁止超过 10 万行的词表：端口全表、账号密码、子目录、子域名、host 碰撞、哈希碰撞都算。禁止 rockyou（~1400 万）与 dirbuster medium（220560）。目录最大用中档 87664；子域/host 只用 dnsmap（17576）；口令最大 metasploit password.lst（88406）。
- 开局策略（CTF 先看入口 vs 红队三圈）见 skill `recon-fanout` / `recon-spiral`。本 skill 只给路径和可复制命令。

# Web 能力（默认工具 + 一条可复制命令）
- 端口扫描：CTF 可用 `timeout 60 /usr/bin/nmap -sV -T4 -Pn --top-ports 100 --open <host>`。红队/SRC **禁止 nmap/masscan**（原始套接字会漏真实 IP），改用 `curl` / `http_request` / `ffuf`。
- Web 指纹：`/usr/bin/whatweb -a 3 <url>`。
- WAF：`/usr/bin/wafw00f <url>`。
- fscan: `/usr/bin/fscan -h <ip> -np`（内网横向时扫C段/24）。
- nuclei：`/usr/bin/nuclei -u <url> -silent -nc`（引擎已装；模板走 nuclei 自己的目录，禁止 which）。
- 域名/子域：`/usr/bin/gobuster dns -d <domain> -w /usr/share/wordlists/dnsmap.txt`（17576 行，本机唯一子域表）。被动/递归：`/usr/bin/amass`、`/usr/bin/fierce`、`/usr/bin/dnsenum`、`/usr/bin/dnsrecon`。无小中大三档子域表，只钉 dnsmap。
- 目录枚举：只用 `/usr/bin/ffuf`，必须 timeout。没有合法「大档」（medium 220560 超 10 万，禁止）。
  - 小：`/usr/bin/ffuf -u http://<host>/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,204,301,302,307,401,403 -t 40`（4614）
  - 中（最大）：`/usr/bin/ffuf -u http://<host>/FUZZ -w /usr/share/wordlists/dirbuster/directory-list-2.3-small.txt -mc 200,204,301,302,307,401,403 -t 40`（87664）
- Host 碰撞：`/usr/bin/gobuster vhost -u http://<ip> --append-domain -w /usr/share/wordlists/dnsmap.txt`；或 `/usr/bin/ffuf -u http://<ip>/ -H 'Host: FUZZ.<domain>' -w /usr/share/wordlists/dnsmap.txt`。
- JS 接口：`python3 <REPO>/tools/JSFinder/JSFinder.py -u <url> -ou js_urls.txt -os js_subs.txt`（仓库 tools/，禁止 which jsfinder）。
- 40x 绕过：已确认 401/403 后 `bash <REPO>/tools/bypass-403/bypass-403.sh http://<host> <path>`（iamj0ker/bypass-403；禁止 which bypass-403）。Payload 被 WAF/拦截页拦住时读 skill `waf-bypass-methodology`。
- 账号密码：`/usr/bin/hydra`（用户 `-L` 密码 `-P`）。一律禁止 `/usr/share/wordlists/rockyou.txt` 与 hashcat 全库。
  - 小：`-L /usr/share/metasploit-framework/data/wordlists/unix_users.txt -P /usr/share/metasploit-framework/data/wordlists/unix_passwords.txt`；HTTP 默认对 `/usr/share/wordlists/metasploit/http_default_userpass.txt`
  - 中：`-P /usr/share/john/password.lst`
  - 大（未超 10 万，红队可用；CTF 不要升到这档）：`-P /usr/share/wordlists/metasploit/password.lst`
- HTTP：`http_request` 优先；`/usr/bin/curl` 仅管道/原始报文。
- sqlmap：仅已确认注入点。`/usr/bin/sqlmap -u <url> --batch --risk=1 --level=1`

# 已装备选（绝对路径；目录默认仍 ffuf，不要四个扫目录工具轮换）
- 目录备选（同一套小/中词表，禁止超 10 万行；ffuf 失败或缺扩展名规则时才换）：
  `/usr/bin/gobuster dir -u http://<host>/ -w /usr/share/wordlists/dirbuster/directory-list-2.3-small.txt`；`/usr/bin/feroxbuster -u http://<host>/ -w /usr/share/wordlists/dirbuster/directory-list-2.3-small.txt`；`/usr/bin/dirb http://<host>/ /usr/share/wordlists/dirb/common.txt`；`/usr/bin/wfuzz -c -z file,/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt --hc 404 http://<host>/FUZZ`
- Web：`/usr/bin/nikto -h <url>`（仅已确认 HTTP 面）；`/usr/bin/httpx -u <url> -title -status-code -silent`（探活/标题）；nuclei 扫模板；wafw00f 识别 WAF。
- 口令：`/usr/bin/hydra`、`/usr/bin/medusa`、`/usr/bin/ncrack`、`/usr/sbin/john`、`/usr/bin/hashcat`。词表仍走小/中/大（大档 88406，未超 10 万）。禁止 rockyou 与 hashcat 全库。
- 其它 Web 相关：`/usr/bin/dig`、`/usr/bin/amass`、`/usr/bin/theHarvester`、`/usr/bin/cewl`、`/usr/bin/searchsploit`、`/usr/bin/proxychains4`、`/usr/bin/msfconsole`。

# 横向 / 服务（何时用 + 一条模板）
- `/usr/bin/ssh`：已扩容内网的 SSH。本机有客户端。禁止 Kali 直连攻击机 docker 网桥——那不是题内网。
  立足点上常常没有能用的 ssh 客户端：不要用 curl 的 sftp/libssh2 去讲 SSH。
  正路：立足点上把 22 或 SOCKS 转到 Kali（webshell 反连 / `socat TCP-LISTEN` / `ssh -D`），再用本机 ssh 打已 `report_pivot_capability` 的主机。
  `ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ProxyCommand='nc -x 127.0.0.1:<socks> %h %p' user@<in-scope-host>`
- `/usr/bin/sshpass`：题面个位数口令。`sshpass -p '<pass>' ssh ...`。CTF 失败不要升字典。
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
- Impacket（均在 `/usr/bin`）：`impacket-smbclient` 列共享；`impacket-secretsdump` 已授权转储；`impacket-psexec` / `impacket-wmiexec` 已有凭证远程执行。

# Shiro（单目标 Key 字典验证）
- 工具目录与工作目录：`/home/shigure/tools/shiro`；`run_cmd` 使用 Linux 路径。
- 已核实启动环境：`/usr/bin/java`（Zulu Java 8）；JAR `/home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar`；主类 `com.summersec.attack.CLI.MainCLI`。
- 本地 Key 字典：`/home/shigure/tools/shiro/data/shiro_keys.txt`（约 1207 行）。必须从工具目录运行，CLI 按相对路径读取 `data/shiro_keys.txt`；不下载或扩充字典。
- 真实响应出现 Shiro / rememberMe 线索后，可对授权单目标进行探测与 Key 字典验证；禁止批量目标、并发任务或并发启动多个 crack。
- 本地帮助（不请求目标）：`timeout 15 /usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI --help`。
- 探测：`cd /home/shigure/tools/shiro && /usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI detect -u '<authorized-url>'`。
- Key 字典验证：`cd /home/shigure/tools/shiro && /usr/bin/java -cp /home/shigure/tools/shiro/shiro_attack-5.1.1-zulu-8-jfx.jar com.summersec.attack.CLI.MainCLI crack -u '<authorized-url>' `。只运行一轮，找到 Key 后停止；超时、限流、目标响应明显变慢或连续服务错误时停止，不自动重试。
- 已知 Key 可用同一启动前缀与 `crack -K` 单独复核。AES 模式依据已核实配置选择 `--cbc` / `--gcm`，不自动遍历模式与 Gadget。
- 红队/SRC 必须沿用项目出口代理要求，CLI 的 `--proxy` 指向已配置代理；无法确认出口时停止，不擅自直连。
- CTF可以直接注入冰蝎内存马，后续操作通过内存马进行。
- 记录实际请求与响应关键证据；框架识别或 Key 验证成功不能单独作为 RCE 证明。工具原目录 SKILL.md 含超出本任务范围的流程，不得据此扩大操作范围。

# 二进制 / 逆向（绝对路径）
- 识别：`/usr/bin/file`、`/usr/bin/strings`、`/usr/bin/xxd`、`/usr/bin/exiftool`、`/usr/bin/binwalk`
- 反汇编：`/usr/bin/objdump -d <bin>`、`/usr/bin/readelf -a <bin>`、`/usr/bin/nm <bin>`、`/usr/bin/r2 -A <bin>`、`/usr/bin/gdb`
- OCR：`/usr/bin/tesseract <image> stdout`
- Python 仅这些库可用：`z3`、`Crypto`、`sympy`、`PIL`、`capstone`。本机没有 pwntools / gmpy2，不要 which。
