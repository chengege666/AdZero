# AdZero OpenWrt / ImmortalWrt ARM64 公开一键安装测试版

**发布标签：`v0.21.5-arm64-beta.1`（Pre-release）**。这是面向自愿测试者的独立发行通道，不代表真实路由器已通过 LAN DNS、代理共存、重启与故障恢复认证；现有 `v0.21.5` 发布资产、稳定版 SDK 白名单和 LuCI 稳定在线更新均保持原状。APK 本体内部版本仍为 `0.21.5-r1`，使用此前分别通过官方/厂商 SDK 构建的原始包字节，不以新版本号伪装为已重新编译的插件。

## 四组可一键测试的固件

| 固件 | 版本 | `DISTRIB_TARGET` | `DISTRIB_ARCH` | APK 来源 |
| --- | --- | --- | --- | --- |
| OpenWrt | 25.12.6 | `rockchip/armv8` | `aarch64_generic` | 原厂 SDK |
| OpenWrt | 25.12.6 | `mediatek/filogic` | `aarch64_cortex-a53` | 原厂 SDK |
| ImmortalWrt | 25.12.2 | `rockchip/armv8` | `aarch64_generic` | 独立 ImmortalWrt SDK |
| ImmortalWrt | 25.12.2 | `mediatek/filogic` | `aarch64_cortex-a53` | 独立 ImmortalWrt SDK |

这些是**精确固件版本 + target + 包架构**组合，不能因为同属 ARM64 就互换安装包。不适用 OpenWrt/ImmortalWrt 的其他版本，也不适用 iStoreOS（其独立 Beta 安装器请见 [iStoreOS 测试版说明](RELEASE_ISTOREOS_BETA_0.21.5.md)）。

## 一键菜单安装

先确认测试设备有本地 SSH/有线救援途径，备份原有 DNS/代理设置。以 root 身份 SSH 执行：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://github.com/slobys/AdZero/releases/download/v0.21.5-arm64-beta.1/install-arm64-beta.sh -o /tmp/install-arm64-beta.sh && sh /tmp/install-arm64-beta.sh --menu
```

菜单自动选择对应的固件 APK，不需要填写 CPU 型号、版本号或安装文件名：

1. **只读检查**：核对固件、target、ABI、编译产物 SHA 和依赖安装计划；如缺少依赖，可能刷新官方软件仓库索引，但不会安装软件包。
2. **一键安装（默认关闭过滤）**：安装前备份 `/etc/config`，仅安装本体及缺失的原厂软件依赖；不主动调用 DNS 控制器，不自动开启拦截。
3. **安装并启用过滤**：除首次确认外，必须再输入 `YES` 承担可能影响 DNS/代理的风险。
4. **安全卸载**：先调用控制器关闭并恢复 AdZero 管理的设置，失败时停止卸载；保留系统依赖和备份。
0. 退出。

如已安装其他版本 AdZero，会拒绝强行覆盖。请使用原版本安全卸载，保留配置备份后再测试此独立发行渠道。此公测版并不提供原位置覆盖升级功能。

## 依赖处理与官方仓库

与 iStoreOS 的全量离线 7 包不同，**这四组公开 Beta 仅包含本目标 SDK 实际编译的 `luci-app-adzero` APK**。安装器先尝试完全本地的 `apk add --simulate --no-network`；若缺少依赖，才从与当前固件系列、`25.12` 大版本、target、ABI 一致的默认官方 `/etc/apk/repositories.d/distfeeds.list` 仓库刷新软件包索引并重新模拟。默认只允许 `downloads.openwrt.org` 或 `downloads.immortalwrt.org` 的对应官方 HTTPS 仓库；如果路由器使用其他镜像、定制仓库或无法下载依赖，会**停止并提示**，不自动改写现有软件源。

安装器的所有下载测试包均固定 SHA-256；实际 APK 安装之前还会拒绝计划中的软件包**移除、升级、降级或重装**，尤其不会强制把原版 `tcpdump` 替换成 `tcpdump-mini`。所需安装的系统依赖仅来自现有固件对应的官方软件仓库，不自动添加任何第三方源。

打开菜单不安装软件；下载安装只在测试者确认后执行。依赖预检不代表实机网络过滤结果，**首次建议选择选项 2**；确认能正常进入 LuCI、SSH、访问互联网后，再从 LuCI 主动打开过滤。

## 下载包清单与校验

GitHub Pre-release 包含五个主要资产和一个校验清单：

- `install-arm64-beta.sh`：中文菜单与全部四种目标的固定 SHA-256。
- `adzero-openwrt-rockchip-arm64-beta.tar.gz`
- `adzero-openwrt-filogic-arm64-beta.tar.gz`
- `adzero-immortalwrt-rockchip-arm64-beta.tar.gz`
- `adzero-immortalwrt-filogic-arm64-beta.tar.gz`
- `SHA256SUMS`：上述五份文件的 SHA-256。

本地下载的发行文件可执行 `sha256sum -c SHA256SUMS` 检查完整性。SHA 不等于签名或作者身份认证，务必从本项目官方 GitHub Release 获取。

无法直接访问 GitHub 的测试用户可通过可信电脑下载**安装器与其对应的固件专用压缩包**，复制到路由器同一目录，执行 `sh install-arm64-beta.sh --menu --local-dir /tmp/adzero-arm64-beta`；不会绕过固件、依赖和 SHA 校验。

## 测试与问题反馈

建议记录：固件版本和 target（`cat /etc/openwrt_release`，发给他人前检查内容）、一键预检与安装结果、LuCI 是否能打开、开关过滤后的 LAN 正常解析/广告阻断、IPv4/IPv6、NaiLink/PassWall/OpenClash/Nikki 共存、重启保持及安全卸载恢复。不要上传订阅地址、节点、密码、私有 DNS 上游或完整 `/etc/config`。

四套 APK 已有真实 SDK 编译及 LuCI 文件检查证据，见 [ARM64 已编译候选记录](evidence/arm64-pr10-sdk-builds.json)。本次源码仅用于发布明确标记的 **公共 Beta**，四种组合**仍未纳入**稳定版的 `sdk_verified` / `releases.tsv`；固件实体设备的安装与 DNS/代理共存验收有待用户反馈。

