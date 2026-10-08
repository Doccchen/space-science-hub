# 新闻 Agent 公网 IP HTTPS 接入准备

2026-10-08。用户确认目前只有公网 IP、尚无 HTTPS。本轮只读连接现有服务器检查，**未安装软件、未申请证书、未开放云端端口、未部署 Agent，也未更改现有网站。** 此文件及 templates 是可审阅的接入准备，执行前确认下面的授权和条件。

## 已查明与入口

- 服务器 `8.137.164.100`；应用目录 `/opt/space-news`。
- `ss -ltn` 显示网站监听 `0.0.0.0:8080`，管理后台仅 `127.0.0.1:8090`；80/443 未监听。云安全组和主机防火墙的放行状态未验证。
- `command -v nginx certbot docker openssl` 仅返回 Docker 与 OpenSSL；未发现 PATH 中的 Nginx、Certbot。
- 拟建工具入口 `https://8.137.164.100/api/news-mcp/mcp`。这个地址目前尚不可用，百炼对 IP HTTPS 及动态头传递的兼容性须实测。

Let’s Encrypt 已开放 IPv4/IPv6 IP 地址证书，不需要购买域名。IP 证书使用 shortlived profile，有效约 6 天（160 小时），必须自动续期。Certbot 官方 IP webroot 用法要求 5.4 或更高版本；不能照搬旧版 `certbot --nginx -d 域名` 命令。[IP 证书可用性](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)、[Certbot IP 证书指南](https://letsencrypt.org/2026/03/11/shorter-certs-certbot)。

## 执行前需确认

1. 用户同意在这台服务器安装 Nginx/隔离的 Certbot 并申请 IP 证书，已阅读并同意证书机构服务协议；确定用于证书账户的联系邮箱。不在未获同意时自动传 `--agree-tos`。
2. 阿里云实例安全组/轻量防火墙允许 TCP 80（HTTP-01 验证）与 443（TLS）。只需这两个端口，管理后台 8090 不公开。
3. 公网 IP 稳定且能从 Let’s Encrypt 验证节点访问 80。不要使用自签名证书或要求百炼关闭证书验证。
4. 下面的配置是**仅供 MCP 的 TLS 网关**，其他 HTTPS 路径返回 404；保留现有 8080 网站。正式开放网页问答前还要迁移整站 HTTPS、核实 FastAPI 的可信代理/Origin/Cookie 设置，不能以工具 TLS 入口代替整个网站上线验收。

## 配置文件

- `tools/templates/news-mcp-ip-acme.conf`：第一阶段只开启 HTTP-01 challenge。
- `tools/templates/news-mcp-ip-https.conf`：证书就绪后接替同一个 Nginx 站点，代理准确的 MCP 路径；保留 Authorization 和 X-News-Context；关闭响应缓冲并设置长连接超时。
- `tools/templates/news-mcp-certbot-renew.service` 与 `.timer`：每日四次检查续期，实际到期策略由 Certbot 决定；只有续期成功才校验并 reload Nginx。

不将 API Key 或工具密钥放入 Nginx 文件。服务端仍校验短效任务上下文；这份代理不会自行提供跨新闻访问许可。

## 拟执行步骤（不是已执行记录）

上传模板到 `/opt/space-news/tools/templates/` 后：

1. 备份任何既有 Nginx 配置；安装发行版 Nginx 和 Python venv 支持，使用 `/opt/space-news-certbot` 独立虚拟环境安装 `certbot>=5.4,<6`，检查实际版本支持 `--ip-address` 和 `--preferred-profile`。安装失败先定位网络/包兼容性，不修改 Docker 全局配置。
2. 创建 `/var/www/space-news-acme/.well-known/acme-challenge/`，复制 bootstrap 模板到 `/etc/nginx/sites-available/space-news-mcp` 并建立 sites-enabled 链接。运行 `nginx -t` 后启用；不覆盖已有 default/其他站点，有冲突则检查后处理。
3. 放置一次性非敏感 challenge 文件，分别从服务器与外部访问 `http://8.137.164.100/.well-known/acme-challenge/文件名`，证实 HTTP-01 可达。
4. 获得协议与邮箱确认后，先用 staging 证书验证流程；staging 证书不受信，只用于申请链路，不能提供给百炼。正式申请使用生产 ACME 服务，例如（邮箱为待填变量）：

   ```bash
   /opt/space-news-certbot/bin/certbot certonly \
     --webroot --webroot-path /var/www/space-news-acme \
     --preferred-profile shortlived \
     --ip-address 8.137.164.100 \
     --cert-name 8.137.164.100 \
     --email "$CERTIFICATE_CONTACT_EMAIL" --agree-tos --non-interactive
   ```

5. 检查 `/etc/letsencrypt/live/8.137.164.100/` 实际证书路径、有效期和 SAN IP；将同一个 Nginx 站点文件换成 HTTPS 模板，`nginx -t` 后 reload。模板中的 cert-name 与命令一致，若续期账户已存在别名需按实际结果调整。
6. 安装提供的 systemd service/timer，`systemctl daemon-reload`、启用 timer，执行 `certbot renew --dry-run --cert-name 8.137.164.100` 及 hook 检查；查看下一次运行时间和失败日志。部署完成后还需观察首次真实续期结果，不能仅以配置了 timer 宣称续期已验收。
7. 从外部使用正常 TLS 校验访问工具路径，不使用 curl `-k`。缺少 Agent 后端时可能是 404；默认关闭可能返回 503；开启且无鉴权应为 401。状态码必须结合后端版本/开关解释，不能仅看到连接成功就宣称 MCP 可用。
8. 按开发方案单独打包、备份和部署新闻后端，初始开关关闭；配置 Key/主密钥、工具鉴权和可信上下文。证实百炼动态转发 X-News-Context，才允许打开 MCP 模式。现在尚不能将 NEWS_MCP_CONTEXT_VERIFIED 设为 1 来绕过验证。

## 验证与回退

上线前验证证书正常受信、准确 endpoint 的 SDK initialize/tools/list/tools/call、无令牌拒绝、跨新闻/过期令牌拒绝、每任务调用预算和正文完整读取证据。测试期间不要在 HTTP 链路发送工具密钥，不打印密钥或原文工具输出。

如 HTTPS 配置失败，恢复本轮备份的站点配置，禁用本轮 timer 和新增站点，`nginx -t` 后 reload；保留诊断证据，现有 8080 网站与数据卷不变。不得卸载或覆盖不属于本轮的 Nginx 配置。此入口在撤回时关闭 MCP 开关并撤销工具密钥，证书和 ACME 账户按证书机构流程处理。
