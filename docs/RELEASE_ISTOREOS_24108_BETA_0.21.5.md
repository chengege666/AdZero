# AdZero iStoreOS 24.10.8 原生 OPKG / IPK 一键安装公测

发布标签：**`v0.21.5-istoreos-24108-beta.1`（公开 Pre-release）**。

这是专门为 iStoreOS 24.10.8 原厂固件制作的独立 IPK 安装渠道，不等于 24.10.x 全系列通用，也不代表所有实体设备通过了稳定验收。它与 iStoreOS 25.12.6 的 APK Beta.3 **完全分离**，不能混装。

## 严格支持的三个目标

| 原厂固件（必须一致） | 设备 target | 包架构 | 软件包 |
| --- | --- | --- | --- |
| iStoreOS 24.10.8 / **2026073111** | `x86/64` | `x86_64` | 原厂 Buildroot LuCI IPK + 7 个原厂依赖 |
| iStoreOS 24.10.8 / **2026073111** | `armsr/armv8` | `aarch64_generic` | 原厂 Buildroot LuCI IPK + 7 个原厂依赖 |
| iStoreOS 24.10.8 / **2026073111** | `rockchip/armv8`（官方 R6XS 板型） | `aarch64_generic` | 原厂 Buildroot LuCI IPK + 7 个原厂依赖 |

使用 **root SSH** 运行 AdZero 唯一的统一安装命令，无需手动指定架构：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

程序会识别固件 ID、完整版本、`DISTRIB_REVISION`、target、包架构、OPKG 数据库，以及 R6XS 原厂板型。遇到 24.10.7、其他修订号、错误架构、APK 固件或非官方 R6XS 板型会在安装前拒绝。

菜单提供：1 只读预检；2 一键安装但**默认关闭 DNS 过滤**；3 明确再次确认风险后安装并开启；4 安全卸载（先关闭并恢复 AdZero 管理的 DNS/代理设置）；0 退出。安装前会备份 `/etc/config`，保留原来的共享软件包和备份，不强行覆盖已经安装的其他 AdZero。

## 安全保护与离线依赖

- 发行包有 3 份固件专用 `tar.gz`，各自只包含 1 个真实原厂源码 Buildroot 打包的 `luci-app-adzero_0.21.5-r1_all.ipk` 和 7 份从本机原厂 24.10.8 feeds 下载的 IPK；加上元数据，总共 11 项。
- 安装器固定校验发行压缩包 SHA-256、内部每个文件 SHA-256、完整固件/target/ABI 和原厂 OPKG 软件包数据库，然后运行 `opkg --noaction install`。检测到升级/删除系统包、文件冲突或依赖不能闭环时直接停止。
- 不会替换原厂完整版 `tcpdump`；无须添加外部/跨厂商软件源；正式安装使用本地已经校验的八个 IPK。
- 首次请选择选项 **2**，先检查 SSH/LuCI/正常上网/原代理能否正常使用；确认后再主动启用过滤。若缺少本地救援方式，不建议在唯一生产路由器上首次试装。

安装器本身也可以用以下命令先执行只读检测（需要本次发布包可下载）：

```sh
sh /tmp/adzero-install-auto.sh --check
```

## 已完成的验证

三份原厂 iStoreOS 24.10.8 固件镜像均完成 gzip、RAW、SquashFS 固件版本/target/ABI 校验，包含 1041、1001、922 个原装 OPKG 软件包。三份原厂历史 Buildroot 源码与全部 **38 组 feeds 固定提交**一致。使用各自的真实 LuCI 打包规则生成了 3 个架构为 `all` 的原生 AdZero IPK，且校验过真实 OPKG gzip-tar 封装、包头版本和依赖。

每个原厂固件分别下载并校验 7 个尚未预装的原厂依赖包，共 21 个。使用从原厂固件提取的 **真实 OPKG 程序、原始 installed 数据库和所有已安装文件清单**，分别对「真实编译的 AdZero IPK + 七个原厂依赖」完成离线 `--noaction` 模拟：各新增 8 包，0 个原有包被升级/删除/重装，没有文件冲突警告，数据库 SHA-256 保持不变。

源代码的**历史厂商 Git 提交**可确认，但原厂 24.10.8 镜像没有发布可独立证实镜像构建所用精确 Git HEAD 的 `commit.buildinfo`。本项目明确把这一点标记为 **historical source exact factory revision not attested**；本次为独立公测，不视为原厂 SDK 完整认证。由于 LuCI 软件包不含 eBPF 编译代码，打包时跳过了无关的 LLVM/BPF 主机工具构建，不影响包的 OPKG 原生封装。

已验证不等于实机验收：**尚未在全部实体设备测试 LAN IPv4/IPv6 DNS、PassWall/NaiLink 等代理共存、重启和失败恢复**。

## 如何反馈

建议提供 `cat /etc/openwrt_release`（脱敏）、是否自动识别进入正确菜单、安装报错、正常网站/DNS/代理测试、重启后状态以及安全卸载是否恢复。不要上传代理订阅、token、密码、完整 `/etc/config` 或私人域名。

[GitHub Issues](https://github.com/slobys/AdZero/issues) · [兼容性与详细证据](ISTOREOS_24_10.md) · [统一安装手册](https://slobys.github.io/AdZero/installation.html)

本次不会修改稳定版 `v0.21.5`、原有 iStoreOS 25.12 Beta.3、ARM64 Beta.2 的任何软件包和 LuCI 稳定在线更新。
