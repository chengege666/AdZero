# AdZero iStoreOS 25.12.6 Beta.4：旧版一键修复与安全卸载

版本：**`v0.21.5-istoreos-beta.4`**（独立 Pre-release；不是稳定版认证）。

本次专门解决用户在原厂 iStoreOS 25.12.6 x86/64 遇到的「系统检测到已有 AdZero，无法安装；选择卸载时又找不到 Beta 安装标记」的闭环问题。

## 适用范围

只支持 **iStoreOS 25.12.6，修订号 `2026102312`** 对应三个原厂 target：

| 目标 | 包架构 | 说明 |
| --- | --- | --- |
| `x86/64` | `x86_64` | AMD / Intel 软路由 |
| `armsr/armv8` | `aarch64_generic` | 原厂 ARMSR |
| `rockchip/armv8` | `aarch64_generic` | 原厂 R6XS 板型白名单 |

不支持 iStoreOS 24.10.x 的 OPKG/IPK，也不会复用其他厂商 APK。

## 用户只需一条命令

通过 root SSH 执行：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

中文菜单现在包含「2）一键安装/安全修复已有 AdZero」「4）安全卸载当前 AdZero（包括没有 Beta 标记的旧版）」「5）只读检测安装来源、包版本、接管状态」。操作失败会回到同一个菜单，无须再下载脚本。首先选择 5 可不修改网络地确认状态。

- **全新安装**：严格验证官方固件、原厂七份 APK 的 SHA、架构和离线依赖模拟，安装后默认不启用 DNS 过滤。
- **同版本、无 Beta 标记**：必须由真正的 APK 数据库确认包安装、由 APK 文件清单确认控制程序归属，且版本精确为 `0.21.5-r1`；仅对 AdZero 本体执行离线模拟和 `--force-reinstall`，不重装依赖、不中途使用在线软件源。先备份并安全恢复旧版的 DNS/代理设置。
- **不同版本的旧 AdZero**：为避免覆盖不兼容配置，不直接强制升级；在相同菜单选择 4，完成安全恢复和本体卸载，再选 2 安装。共享依赖与备份保留。
- **已带已知 Beta 标记**：识别已有安装，不重复执行安装。卸载前也会核对来源、所有权、依赖变化计划。
- **孤立配置、非 APK 所有者、版本不明、锁冲突、异常符号链接、依赖计划不安全或 DNS/代理恢复失败**：拒绝修改，不允许自动删除原系统文件。配置与状态备份在 `/etc/adzero-backups`。

Beta.4 使用的 AdZero 本体 APK 和六份原厂依赖与 Beta.3 **完全相同**；升级内容仅安装器和独立发行包的元数据。原厂已安装包原版 `tcpdump` 不应被替换。

## 验证与限制

三个目标有原厂来源、SHA 和隔离测试。对比 Beta.3 公开原文件与 Beta.4 新发行文件，确保本体 APK 的 SHA-256 一致且稳定兼容矩阵未改变。已在原厂 iStoreOS 25.12.6 x86/64 镜像的完全断网 QEMU 虚拟机中，使用真实 APK 3.0.5 和已发布的 Beta.3 归档进行实测：实际安装旧版→模拟无 Beta 标记→新 Beta.4 只读检测→**仅重装 AdZero 本体**→**成功安全卸载**，均完成且输出 `ADZERO_GUEST_BETA4_LIFECYCLE_PASS`。原始镜像校验、发行字节 SHA、虚拟机边界和详细检查结果见 [发布证据](evidence/istoreos-25.12.6/public-beta-0.21.5-beta4-assets.json)。

**这不是实体设备稳定性认证。** 原厂 ARM64 设备的 LAN IPv4/IPv6、NaiLink/PassWall、DNS、重启和故障恢复仍需自愿测试者反馈。不要在唯一生产路由器且无本地救援手段的情况下首次开启拦截。

反馈只需要固件版本、菜单 5 的非敏感状态和脱敏后的错误信息；不要上传密码、代理订阅、私有域名、原始 `/etc/config` 或密钥。

[Beta.4 Release](https://github.com/slobys/AdZero/releases/tag/v0.21.5-istoreos-beta.4) · [统一安装手册](https://slobys.github.io/AdZero/installation.html) · [GitHub Issues](https://github.com/slobys/AdZero/issues)。
