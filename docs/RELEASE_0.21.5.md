# AdZero v0.21.5 · ImmortalWrt 官方 SDK 扩展与 iStoreOS 独立构建

**测试版（Pre-release）**：五组 v0.21.5 对应 SDK 全部完成独立编译，GitHub Windows、Linux、官方 OpenWrt ash 测试通过；实际发行文件在 10 组隔离安装/升级/恢复回归中通过。**真实路由器 DNS、代理共存与故障回滚验收仍未完成**。

本版保留 v0.21.4 的 LuCI 点击在线更新、中文安装菜单、配置备份和故障恢复，新增 ImmortalWrt 的两个精确 x86_64 固件版本。所有其他版本仍需要独立 SDK 适配，不能把 x86_64 CPU 相同理解为 ABI 相同。

## SDK 已验证的新增目标

| 固件 | 完整版本 | target | 包管理器 | SDK 结果 |
| --- | --- | --- | --- | --- |
| ImmortalWrt | 24.10.6 | x86/64 | OPKG / IPK | 厂商 SDK 独立编译和文件验证通过 |
| ImmortalWrt | 25.12.2 | x86/64 | APK | 厂商 SDK 独立编译和文件验证通过 |

最初使用 AdZero v0.21.4 源码验证两个厂商 SDK 能够独立编译，证据见 docs/evidence/v0.21.5/vendor-sdk-builds.json。正式 v0.21.5 已使用更新后的同一份源码在五套匹配 SDK 上全部重新编译、生成独立安装包并校验 SHA-256，**没有复用 v0.21.4 二进制文件**。

## iStoreOS 进展

已验证 iStoreOS 最新 x86_64 25.12.6-2026102312 的完整官方固件镜像 SHA-256，并直接读取镜像内真实系统值：

- DISTRIB_ID = iStoreOS
- DISTRIB_RELEASE = 25.12.6
- DISTRIB_REVISION = 2026102312
- DISTRIB_TARGET = x86/64
- DISTRIB_ARCH = x86_64
- 包管理器 = APK（镜像中 /lib/apk/db/installed）

厂商源码提交、13 组 feeds 和宿主工具已完成独立准备，匹配的原生 APK 和真机验证**尚未完成**。iStoreOS 暂不列入 sdk_verified 或 releases.tsv，后续构建需要同时校验完整发行版修订号，不能只看 25.12.6。

## 安装和安全边界

现有 v0.21.4 用户可以点击 LuCI Logo 旁的版本号检查更新；升级前将先通过 SDK 包、依赖、SHA-256 预检，失败则提示原因。未安装用户仍可使用仓库 README 中固定的一条 SSH 菜单命令。

**真实路由器的 DNS、代理共存、重启和卸载回滚验收仍未完成；本版为测试性质，不是全机型稳定认证。**
