# AdZero v0.5.0 设备验收

状态：**未执行真实路由器与 LAN 验收**。当前公开测试包有两个官方 SDK 的构建证据；下列内容是待执行清单。

先记录固件完整版本、target、包架构、OPKG/APK、代理/核心/adblock-fast 版本和网络拓扑，备份配置，准备本地登录和救援方式。NaiLink 节点、各代理的订阅和凭据不应因测试而更改。恢复日志可能含原有 DNS 配置，不公开上传原文。

## 安装、启停与生命周期

- [ ] 一键脚本能正确识别 OpenWrt 24.10.8 x86/64 IPK 和 25.12.5 x86/64 APK。
- [ ] 未验证版本、厂商、target、架构、双包管理数据库和错误 SHA-256 在安装前失败。
- [ ] /etc/config 备份存在且权限受限，依赖来自当前固件源，没有升级其他软件包。
- [ ] 直接装包默认关闭；一键脚本默认启用；--no-enable 只安装。
- [ ] LuCI 复用现有会话，开关/刷新/重查可用，无二次登录和多余 RPC 权限。
- [ ] force_dns=0、严格 HTTPS 验证生效；关闭后只恢复自己管理且未被外部改变的值。
- [ ] 空规则、下载失败、证书错误不显示过滤成功。
- [ ] 重复启用和内容不变的同步不重复加规则、不重启代理、不反复写闪存。
- [ ] 更新、订阅刷新、代理重载、路由器重启之后规则仍在有效配置中。
- [ ] 正常卸载先恢复自有入口；IPK/APK 的真实 prerm/升级/服务钩子行为逐一检查。
- [ ] 迁移旧版前先关闭保护；恢复失败时记录仍在，不能删除日志掩盖问题。

## 四个代理分别测试

NaiLink：检查 CGI 网关、临时 session 的创建/销毁、parsedDns/updateDns/run。原上游和其他路由不变，自有 GeoSite DAT 能加载。检查 daemon 重启、DNS profile 切换/编辑、eBPF 与 IPv4/IPv6。API 写前复读仍不是原子条件更新，需并发编辑测试。

PassWall：检查 block_host 自有块、use_block_list，以及 dnsmasq、ChinaDNS-NG、SmartDNS 生成结果。独立验证直连/代理列表和设备 ACL 优先级。关闭时用户新加的域名保留。

OpenClash：检查 custom_overwrite 在现有 exit 0 前执行，订阅原文不变，生成配置中有 provider/policy/Fake-IP 排除。Meta -t 失败应停止适配。检查订阅刷新和核心版本变化；旧版 Clash 不按 Mihomo 认证。

Nikki：检查 mixin 开关、nikki-rules 前置、Fake-IP 数组和最终运行配置，现有过滤项仍在。core_only、禁用但有内容的混入应拒绝自动开启。检查 UCI 后置混入不会覆盖自有 DNS 条目。

无代理、PassWall 2、多代理、未知核心和 AdGuard Home 冲突分别记录；当前后三类不应自动接管。

## 实际 DNS 查询

从 LAN 客户端查询一条当前有效列表中的域名及其子域名，再查询正常控制域名。分别覆盖 UDP/TCP、A/AAAA、IPv4/IPv6 传输、路由器 DNS 与代理核心 DNS。

~~~sh
dig @ROUTER_IP BLOCKED_DOMAIN A
dig @ROUTER_IP BLOCKED_DOMAIN AAAA +tcp
dig @ROUTER_IP NORMAL_DOMAIN A
~~~

这些是模板，需填入实际地址/域名。NaiLink reject、PassWall 各后端和 Mihomo 的应答形式可能不同；核对实际规则命中，不能仅以超时证明被拦截。正常域名须保持可用。

额外测试 Fake-IP、TUN/eBPF、多 dnsmasq、非默认端口、ACL、终端 DoH/DoT、外部 DNS 和绕过路径。仅代理连接被 REJECT 不能冒充 DNS 已返回 NXDOMAIN；路由器自身查询成功也不能代替 LAN 设备测试。

## 故障注入与稳定性

- [ ] 下载失败、磁盘满、写入/commit 失败、核心检查失败和持续/单次重启失败。
- [ ] 刷新失败恢复上一份有效规则；恢复失败保留 recovery_required。
- [ ] 外部改变 force_dns/TLS/混入文件/profile/provider 后不覆盖新配置。
- [ ] 断电后 preparing/restarting/restoring 日志不能被当成正常启用。
- [ ] 启停、更新、订阅刷新前后代理连通、正常网页、局域网设备发现保持可用。
- [ ] 峰值内存、剩余闪存、启动延时和规则更新写入量可接受。

每个组合独立保存去除凭据后的结果和包哈希。所有真实设备项完成后，才能提升该组合的稳定认证等级。
