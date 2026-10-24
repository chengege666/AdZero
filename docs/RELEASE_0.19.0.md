# v0.19.0：统一 DNS、组内并发与严格路径保护

配置地址、选择单一或并发策略、设置 SOCKS5 端口和严格模式，统一在运行概览的「DNS 与分流」完成。增强页显示并测试同一份配置。升级沿用旧模式，新开关默认关闭。

## 核心实现

- `routing-lib.uc`：兼容旧配置，限制并发至同组最多三个地址；Mihomo 原生数组，NaiLink 保留原生缓存与域名映射。
- `dns-pool-lib.uc` / `dns-pool.uc`：回环监听、有界并发、两秒查询期限，校验问题与应答一致性；国外 SOCKS5 路径失败不直接重试公共 DNS。
- `adzero-dns`：只在拥有并发入口记录时提前启动，避免代理启动与节点解析互相等待；严格模式重启后先按恢复记录建立阻断，再由主服务核对当前 LAN 和代理路径。
- `dns-guard.uc` / `dns-guard-lib.uc`：独立且核对所有权的 nft 表、DNS 恢复记录、代理交接时阻断、UDP/TCP 应答确认；默认 LAN 变化后重新阻断，不沿用旧的“已保护”状态。
- `adapter.uc` / `ctl` / `watch`：沿用既有事务和锁，内部迁移保留保护，已确认的旧 DNS 会话按精确范围清理；后台不排队争抢操作锁。测试专用端口变化不触发单一模式代理重载。
- LuCI：统一编辑、待应用与保存状态，严格模式不提供会退出保护路径的临时暂停；增强 CNAME／设备入口暂不与严格路径叠加。

## 兼容性与边界

OpenClash / Nikki 使用原生多上游；NaiLink 严格模式必须有经验证的本机无认证 SOCKS5。PassWall 保留原有 dnsmasq / ChinaDNS-NG 引擎；国外并发要求原生 TCP DNS 和 SOCKS5，严格 TCP 模式也使用该明确路径，不依赖透明代理端口排除规则。Xray / sing-box 的不支持组合会拒绝应用，不静默改引擎或节点。

严格模式覆盖确认的默认 IPv4 LAN 明文 DNS 路径，阻断该 LAN 的 IPv6 DNS 和 853；国内生效组保留节点引导解析例外。浏览器／应用 DoH、其他 VLAN、VPN 等不能被这一模式完整覆盖。普通 TCP DNS 不等于加密 DNS。完整条件见 [DNS 设置](DNS_SETTINGS.md)。

## 验证与发行

测试、实际 SDK 包检查与安装器交付记录保存在 [验证摘要](evidence/v0.19.0/summary.json)。区分原生 ucode/UCI、真实内核命名空间、Mihomo 核心、dae 语法解析、NaiLink CGI/API-only 和服务／上游夹具；均不作为真实路由器与终端验收证明。

仅发布三个已验证的 SDK 目标：OpenWrt 24.10.8 x86/64 IPK，25.12.5 x86/64 APK，以及 25.12.5 rockchip/armv8 APK。源码摘要、包内文件权限与下载摘要分别核对；本次没有连接或修改用户路由器。
