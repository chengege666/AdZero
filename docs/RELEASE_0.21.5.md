# AdZero v0.21.5 · ImmortalWrt 官方 SDK 扩展与 iStoreOS 独立构建

**发行候选版（待 SDK v0.21.5 新构建、GitHub CI 和设备验收）**。

本版保留 v0.21.4 的 LuCI 点击在线更新、中文安装菜单、配置备份和故障恢复，新增 ImmortalWrt 的两个精确 x86_64 固件版本。所有其他版本仍需要独立 SDK 适配，不能把 x86_64 CPU 相同理解为 ABI 相同。

## SDK 已验证的新增目标

| 固件 | 完整版本 | target | 包管理器 | SDK 结果 |
| --- | --- | --- | --- | --- |
| ImmortalWrt | 24.10.6 | x86/64 | OPKG / IPK | 厂商 SDK 独立编译和文件验证通过 |
| ImmortalWrt | 25.12.2 | x86/64 | APK | 厂商 SDK 独立编译和文件验证通过 |

首次验证使用 AdZero v0.21.4 源码，两个 SDK 产物经 GitHub Actions、LuCI 页面交互与独立封装校验成功，见 docs/evidence/v0.21.5/vendor-sdk-builds.json。**v0.21.5 发布须从新版本源码分别重建所有五个 SDK 安装包，并重新核对版本和 SHA-256；禁止直接复用旧 v0.21.4 文件。**

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
