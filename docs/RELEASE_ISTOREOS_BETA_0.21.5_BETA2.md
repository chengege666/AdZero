# AdZero iStoreOS 25.12.6 Beta.2

**发布标签：`v0.21.5-istoreos-beta.2`（公开预发行测试版）**

继续支持 iStoreOS **25.12.6、修订号 2026102312** 的 x86_64、ARM64 ARMSR，以及原厂兼容的 Rockchip R6XS 三个目标。原厂 Buildroot 实际编译的 AdZero APK 和六个配套依赖**字节保持不变**；本次主要加强设备兼容判断和卸载恢复。

## 这次改进

- Rockchip R6XS 额外拒绝无法读取或以符号链接伪装的 `/tmp/sysinfo/board_name`；只有官方 R6XS 镜像名单中的五种板型可进入安装预检。
- 新菜单兼容 **Beta.1 的安装标记**：核对原固件、精确 target、控制器与恢复状态后，可安全卸载旧 Beta.1。
- 卸载前仍会先关闭 AdZero 并恢复其管理的 DNS/代理配置；异常立即停止，保留原配置备份与标记。
- 安装仍使用随每种固件原生编译的 **1 个 AdZero APK + 6 个厂商依赖包**，离线解算、不替换已有原厂 `tcpdump`，默认不启用 DNS 过滤。

## 精确目标

| iStoreOS 版本 | target | 包架构 |
| --- | --- | --- |
| 25.12.6 revision 2026102312 | `x86/64` | `x86_64` |
| 25.12.6 revision 2026102312 | `armsr/armv8` | `aarch64_generic` |
| 25.12.6 revision 2026102312 | `rockchip/armv8`（R6XS 官方板型） | `aarch64_generic` |

## 统一一键安装

通过 root SSH 执行；安装助手会自动选 iStoreOS Beta.2：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

如果此前已安装 Beta.1，请先从新菜单选择「安全卸载」，待 DNS/代理状态确认恢复后，再安装 Beta.2。不允许直接覆盖旧版本。推荐先安装但**关闭过滤**，确认原网络可用后再启用。

[iStoreOS Beta.2 下载页面](https://github.com/slobys/AdZero/releases/tag/v0.21.5-istoreos-beta.2) · [使用手册](https://slobys.github.io/AdZero/installation.html) · [兼容性表](https://slobys.github.io/AdZero/compatibility.html)

## 验收边界

三组原厂 APK/依赖分别经过构建来源与 SHA-256 检查，之前的官方固件数据库离线模拟和 x86 隔离虚拟机证据继续有效。**真实设备的 LAN DNS、NaiLink/PassWall 等代理共存、重启与故障回滚仍须用户试测**。Beta.1 资产保持不变；稳定版 v0.21.5 与公开 `sdk_verified` 白名单没有变更。
