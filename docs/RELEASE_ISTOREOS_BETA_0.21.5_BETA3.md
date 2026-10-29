# AdZero iStoreOS 25.12.6 Beta.3：修复 APK 误判

**版本：\`v0.21.5-istoreos-beta.3\`（公开预发行测试版）**

有真实用户反馈：在 iStoreOS 25.12.6（修订号 2026102312）运行统一安装命令后，提示 **“目标需要 APK，当前包管理器或已安装数据库不匹配”**，导致无法进入中文安装菜单。

## 修复内容

- **统一安装器**不再要求 APK 数据库必须位于固定的 \`/lib/apk/db/installed\`，也不会因为存在旧版遗留的 \`/usr/lib/opkg/status\` 文件就误判系统仍使用 OPKG。
- **iStoreOS 专用安装器**同样改为调用真实的 \`apk info -e\`（只读）检查当前已安装的 \`base-files\`、\`luci-base\`、\`rpcd\` 和完整版 \`tcpdump\`。确实缺少必要组件、原生 APK 不可用或包架构不匹配时仍拒绝安装。
- 保留 **精确固件版本、2026102312 修订号、target/ABI、R6XS 原厂板型、SHA-256、原厂依赖闭环、离线模拟与安全卸载**等保护。
- 新版菜单可以安全识别 **Beta.1 和 Beta.2** 的安装标记，优先恢复 AdZero 管理的 DNS/代理状态后再卸载，不会强制覆盖安装。
- APK 本体与 6 个原厂依赖**字节与 Beta.2 完全一致**；仅安装脚本、菜单检查和发行元数据更新。首次安装默认**不启用 DNS 过滤**。

## 适用设备

仅 **iStoreOS 25.12.6，修订号 2026102312**：

| 固件 target | CPU 架构 | 发行包 |
| --- | --- | --- |
| \`x86/64\` | \`x86_64\` | 原厂 x86_64 APK + 6 依赖 |
| \`armsr/armv8\` | \`aarch64_generic\` | 原厂 ARMSR APK + 6 依赖 |
| \`rockchip/armv8\`（官方 R6XS） | \`aarch64_generic\` | 原厂 R6XS APK + 6 依赖 |

不支持其它 iStoreOS 版本、其它修订号或所有 Rockchip ARM64 通用安装。

## 一条命令，自动进入匹配菜单

以 root SSH 登录软路由，直接执行：

\`\`\`sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
\`\`\`

首次推荐选择 **“一键安装（默认关闭过滤）”**。确认 SSH、LuCI、正常网站与原代理正常后，再手动开启广告过滤。已安装 Beta.1/Beta.2 的设备若要重装，先在新菜单选择「安全卸载」，不要直接覆盖。

想单独测试是否被错误识别，可运行 \`sh /tmp/adzero-install-auto.sh --detect\`（只读、不联网）。如果依然提示 APK 检查失败，可在 SSH 执行以下**只读**命令并将脱敏结果提交到 GitHub Issues：

\`\`\`sh
cat /etc/openwrt_release
apk --print-arch
apk info -e base-files luci-base rpcd tcpdump
\`\`\`

请不要发布代理订阅地址、账号密码、API 密钥及私人网络配置。

## 验证结果与范围

通过真实原厂 iStoreOS 25.12.6 **ARMSR 与 R6XS 固件的 APK 软件包数据库**以及原厂 apk-tools 只读查询验证：遗留 OPKG 标记存在时仍可正确识别，缺失真正的 APK 已安装信息则会安全拒绝。三个目标的中文菜单、安装/卸载、R6XS 设备限制、旧 Beta 恢复和哈希篡改拦截均有隔离回归测试；所有 APK 实际二进制与 Beta.2 已核对一致。

**尚未在截图用户的真实路由器上执行安装，也未宣称 LAN DNS、代理共存与回滚全部完成实机认证。**

[Beta.3 发布下载页](https://github.com/slobys/AdZero/releases/tag/v0.21.5-istoreos-beta.3) · [在线统一安装教程](https://slobys.github.io/AdZero/installation.html) · [提交反馈](https://github.com/slobys/AdZero/issues)

本次不会修改稳定版 \`v0.21.5\`、OpenWrt/ImmortalWrt ARM64 Beta.2 或此前的 iStoreOS Beta.1/Beta.2 发布资产。
