# 新闻 Agent 公网 IP HTTPS 接入准备

2026-10-08。最初用户确认只有公网 IP、尚无 HTTPS，本轮先进行只读检查并准备配置；随后获用户授权实施。本文前半部分保留接入设计与执行条件，实际部署结果见文末。新闻 Agent 后端仍未部署。

**后续执行更新：用户已授权 IP HTTPS 配置并提供证书账户联系邮箱，Nginx/Certbot、正式 IP 证书、TLS 网关与续期定时器已落地。以下“尚未执行”的段落保留最初准备背景；实际状态以本文末尾执行记录为准。新闻 MCP 后端仍未部署。**

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
6. 安装提供的 systemd service/timer，`systemctl daemon-reload`、启用 timer，执行 `certbot renew --dry-run --cert-name 8.137.164.100 --no-random-sleep-on-renew --run-deploy-hooks --deploy-hook "nginx -t && systemctl reload nginx"` 及 hook 检查；人工验证跳过随机等待，正式 service 保留等待。查看下一次运行时间和失败日志。部署完成后还需观察首次真实续期结果，不能仅以配置了 timer 宣称首次真实续期已验收。
7. 从外部使用正常 TLS 校验访问工具路径，不使用 curl `-k`。缺少 Agent 后端时可能是 404；默认关闭可能返回 503；开启且无鉴权应为 401。状态码必须结合后端版本/开关解释，不能仅看到连接成功就宣称 MCP 可用。
8. 按开发方案单独打包、备份和部署新闻后端，初始开关关闭；配置 Key/主密钥、工具鉴权和可信上下文。证实百炼动态转发 X-News-Context，才允许打开 MCP 模式。现在尚不能将 NEWS_MCP_CONTEXT_VERIFIED 设为 1 来绕过验证。

## 验证与回退

上线前验证证书正常受信、准确 endpoint 的 SDK initialize/tools/list/tools/call、无令牌拒绝、跨新闻/过期令牌拒绝、每任务调用预算和正文完整读取证据。测试期间不要在 HTTP 链路发送工具密钥，不打印密钥或原文工具输出。

如 HTTPS 配置失败，恢复本轮备份的站点配置，禁用本轮 timer 和新增站点，`nginx -t` 后 reload；保留诊断证据，现有 8080 网站与数据卷不变。不得卸载或覆盖不属于本轮的 Nginx 配置。此入口在撤回时关闭 MCP 开关并撤销工具密钥，证书和 ACME 账户按证书机构流程处理。

## 实际执行记录

2026-10-08，用户确认按公网 IP 路线继续，强调服务器位于中国大陆且用途为竞赛展示，提供证书联系邮箱。只将邮箱用于用户授权的 CA 账户，不写入 Git 中的脚本或公开 Nginx 配置。核对阿里云官方 [IP 访问网站备案说明](https://help.aliyun.com/zh/icp-filing/basic-icp-service/product-overview/icp-filing-requirements-for-a-regular-website)：直接通过 IP 对外提供网站服务也有备案要求，竞赛用途没有在此说明中列为豁免。本次技术配置不构成备案豁免判断；新 TLS 网关只代理指定 MCP 路径，其他 HTTPS 路径为 404，未把网站通过新 HTTPS 入口公开展示。实际对外使用要求仍需向接入商确认。

- 安装前使用 runtime mask 避免 Nginx 软件包自动开启默认页面；随后安装 Ubuntu Nginx 1.24.0-2ubuntu7.18、python3.12-venv。没有执行系统整体升级或重建应用容器。
- `/opt/space-news-certbot` 隔离环境安装 Certbot 5.8.0，`pip check` 无损坏依赖；没有把 Certbot 放进应用虚拟环境。
- 使用 `tools/setup_news_mcp_gateway.sh` 先 bootstrap。移走本轮新安装生成的 package default 链接至备份，HTTP 80 仅提供 ACME challenge 文件，其余路径为 404。主机 UFW inactive；从本机直接访问 challenge 成功，因此当时云侧 80 已可达。本轮未修改云安全组。
- Let’s Encrypt 测试环境 `certonly --dry-run` 成功，再用用户确认的邮箱与条款同意申请正式 shortlived IP 证书。证书 issuer `Let's Encrypt YE2`，SAN 为 `IP Address:8.137.164.100`。
- 证书有效期：UTC `2026-10-08 05:55:34` 至 `2026-10-14 21:55:33`；北京时间到期为 **2026-10-15 05:55:33**。证书与私钥位于 `/etc/letsencrypt/live/8.137.164.100/`，私钥权限核验为 `600 root:root`，未读取私钥内容。
- 换入正式 HTTPS 模板，Nginx syntax test 成功，reload 成功。外部 curl 使用正常 TLS 验证（未用 `-k`），`ssl_verify_result=0`，根路径和 MCP 路径当时均为 404。根路径 404 符合网关配置；MCP 路径 404 的原因是现有应用镜像中没有 `/app/backend/news_mcp.py`，不能宣称工具已联调成功。
- 安装并启用 `news-mcp-certbot-renew.timer`，每日 00/06/12/18 点附近检查续期，允许随机延迟；查询时下一次检查为北京时间 10 月 8 日 18:13:56。初次人工 renew dry-run 因 Certbot 的随机等待超过 180 秒检查窗口而中止；增加 `--no-random-sleep-on-renew` 后模拟续期成功，deploy hook 的 `nginx -t` 和 reload 成功。正式 service 保留随机等待。首次实际续期仍待运行时验证。
- 手动启动正式 `news-mcp-certbot-renew.service` 验证 systemd 执行，`Result=success`、`ExecMainStatus=0`；当前证书未到期，正常跳过重新签发。oneshot 完成后的 ActiveState=inactive 是预期状态，不表示定时器未启用。
- 原有 `http://8.137.164.100:8080` 健康检查正常，363 篇新闻；app 与 admin 均 healthy、未重建。管理后台仍只绑定服务器回环地址。

服务器备份与执行文件目录：

```text
/root/news-mcp-https-20261008/
  evidence-bootstrap-20261008T065203Z/nginx-before/
  evidence-https-20261008T065449Z/nginx-before/
  latest-evidence-path
```

仍待完成：新闻 Agent 后端部署、独立模型/工具服务端凭据配置、可信动态上下文转发、百炼实际 MCP initialize/list/call 测试。HTTPS 入口可达不等于这些项目完成；现在不应直接把未部署的 404 路径当成可用工具。
