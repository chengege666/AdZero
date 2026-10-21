# 兼容性与证据矩阵

v0.8.2 新增可选规则库与自定义 HTTPS 订阅，保留域名查询、范围放行/撤销和定时暂停/恢复。共享经过后端处理的名单，沿用四个原生代理入口；旧版本的单设备证据不能升级为新功能的真机认证。公开安装清单按以下 SDK 组合生成：

| 固件完整版本 | target / 包架构 | 包格式 | SDK | 设备安装 | LAN 过滤 |
| --- | --- | --- | --- | --- | --- |
| OpenWrt 24.10.8 | x86/64 / x86_64 | IPK | 通过 | 待测 | 待测 |
| OpenWrt 25.12.5 | x86/64 / x86_64 | APK | 通过 | 待测 | 待测 |
| OpenWrt 25.12.5 | rockchip/armv8 / aarch64_generic | APK | 通过 | 待测 | 待测 |
| OpenWrt 其他 24.10.x / 25.12.x | 按实际 target | 实际 OPKG/APK | 逐项推进 | 待测 | 待测 |
| ImmortalWrt 24.10.x / 25.12.x | 按厂商 SDK | 实际 OPKG/APK | 待验证 | 待测 | 待测 |
| iStoreOS 对应维护版本 | 按厂商 SDK / 构建号 | 按设备检测 | 待匹配 | 待测 | 待测 |

机器可读计划见 [compatibility-matrix.json](compatibility-matrix.json)。x86/64、rockchip/armv8 之后，按 mediatek/filogic、ipq40xx/generic、ramips/mt7621 逐项扩展；i386、MIPS/MIPS64、RISC-V 仍为候选。

rockchip/armv8 的官方 profiles 元数据与用户回报均为 OpenWrt 25.12.5 r33051-f5dae5ece4，SDK 的 CONFIG_TARGET_ARCH_PACKAGES 为 aarch64_generic，CONFIG_ARCH 为 aarch64。安装器区分固件包 ABI 与 APK 的 CPU 名，接受该目标上 --print-arch 返回 aarch64 或 aarch64_generic；其他 ABI/CPU 组合仍拒绝。不能把这一别名扩展为任意 ARM64 固件兼容。

2026-10-21 用户反馈：v0.5.3 已在该 Rockchip 设备启用，后端载入 66,425 条域名并完成 NaiLink API 配置同步。这是旧版特定设备的安装/配置证据；上表 v0.8.2 的设备安装与 LAN 项目仍待重新验收，不能直接继承为全部通过。

本体使用 shell、ucode、LuCI JS，未捆绑特定 CPU 的 ELF。依赖、字节序、浮点 ABI、固件 feeds 和包管理器仍按目标分别处理。实际包架构优先于 CPU 位数或产品宣传名；all/noarch 不是跨固件认证。

## 代理范围

| 环境 | v0.5.0 处理 | 待补证据 |
| --- | --- | --- |
| 无代理 | 当前解析器的 adblock-fast 输出 | 路由器及终端查询 |
| NaiLink / daed | 本地认证 CGI/API + GeoSite reject | daed API、eBPF、实际 LAN |
| PassWall | 原生 block_host / use_block_list | dnsmasq、ChinaDNS-NG、SmartDNS、ACL |
| OpenClash | 原生覆写钩子 + Meta 内核配置检查 | 不同插件/核心版本、订阅刷新、TUN |
| Nikki | 原生混入 + UCI 数组合并，核对生成配置 | 不同插件/核心版本、重启、TUN |
| PassWall 2 | 识别，拒绝自动接入 | 独立适配实现 |
| 多代理/未知代理 | 检测并拒绝自动修改 | 查明 DNS 所有者 |

Mihomo 的本机真实 DNS 检查覆盖普通/Fake-IP、UDP/TCP、A/AAAA；不涉及 LAN 或路由器防火墙。dae 验证覆盖真实配置解析和 DAT 加载，不启动 eBPF。配置/UCI 事务测试中的服务重启是隔离替身。

精确 procd 实例与共享核心进程分开报告；不凭 Mihomo/Xray/sing-box 进程名推断插件所有者。界面的终端验证字段保持 false，直到有真实设备证据。

## 不自动处理的情况

- 同时有多个启用/运行的代理，或无法识别的代理核心。
- Nikki core_only、禁用但已有内容的混入文件。
- Fake-IP whitelist 模式；不擅自改变原模式语义。
- dnsmasq 放行例外与拦截父域名重叠，无法等价导出给代理。
- 用户改动了自有混入/恢复记录，不能安全覆盖。
- AdGuard Home 运行，或 adblock-fast 由外部启用。
- nftset/ipset 等非纯域名输出模式。

## 认证要求

每个组合记录固件完整版本、SDK/包 SHA-256、target、包架构、后端/代理/内核版本和网络拓扑。必须验收启停、规则更新、订阅更新、重启、升级、卸载和失败恢复，以及 IPv4/IPv6、UDP/TCP、LAN DNS、代理内核 DNS、终端 DoH/DoT 和绕过路径。

证据分层为：源码审阅 → 隔离运行/替身 → SDK → 设备安装 → LAN 终端。前一项不能替代后一项。参见 [DNS_ADAPTERS.md](DNS_ADAPTERS.md)、[LOCAL_VALIDATION.md](LOCAL_VALIDATION.md) 和 [DEVICE_ACCEPTANCE.md](DEVICE_ACCEPTANCE.md)。
