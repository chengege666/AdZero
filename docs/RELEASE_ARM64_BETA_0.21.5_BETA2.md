# AdZero OpenWrt / ImmortalWrt ARM64 Beta.2

**发布标签：`v0.21.5-arm64-beta.2`（公开预发行测试版）**

这次更新改善了 **OpenWrt 25.12.6、ImmortalWrt 25.12.2** 的 Rockchip ARMv8 / MediaTek Filogic 安装兼容性。四份 SDK 编译出的 AdZero APK **未重新编译，也未改变字节**；Beta.2 更新的是安装器和依赖检查。

## 改进内容

- 支持精确对应固件的默认官方 HTTPS 软件源，也支持中科大镜像 `https://mirrors.ustc.edu.cn/openwrt/` 或 `https://mirrors.ustc.edu.cn/immortalwrt/` 的同源路径。
- 只允许当前固件的 **完整补丁版本**（25.12.6 / 25.12.2）或固件本身使用的滚动 `25.12` 仓库；不允许跨版本、不同厂商、不同 target、不同包架构或混用两种版本的源。
- 依赖解算仍会拒绝计划中删除、降级、升级或重装已有系统软件包的操作；用户的软件源文件不会被自动改写。
- 新安装器可以识别 **Beta.1 的既有安装标记**，允许在校验同一固件 target、控制器恢复成功后安全卸载。需要从 Beta.1 切换到 Beta.2 时，**先在菜单安全卸载，再重新安装**；不执行覆盖升级。
- 首次安装仍然**默认不启用广告过滤**；只有测试者明确选择、确认后才会开启。

## 支持的四组精确目标

| 固件 | 完整版本 | target | 包架构 |
| --- | --- | --- | --- |
| OpenWrt | 25.12.6 | `rockchip/armv8` | `aarch64_generic` |
| OpenWrt | 25.12.6 | `mediatek/filogic` | `aarch64_cortex-a53` |
| ImmortalWrt | 25.12.2 | `rockchip/armv8` | `aarch64_generic` |
| ImmortalWrt | 25.12.2 | `mediatek/filogic` | `aarch64_cortex-a53` |

## 安装方法

使用主分支维护的 **统一安装器**；它会自动识别固件、选择并验证对应 Beta.2 发行脚本，然后打开中文安装菜单。

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

推荐第一次选择「安装但不启用过滤」，确认 SSH、LuCI、正常网页以及原代理仍工作，再主动开启。遇到源不匹配或依赖升级风险，安装器会拒绝安装，**不要强行跨版本装包**。

[ARM64 Beta.2 下载页面](https://github.com/slobys/AdZero/releases/tag/v0.21.5-arm64-beta.2) · [固件兼容性表](https://slobys.github.io/AdZero/compatibility.html) · [详细使用手册](https://slobys.github.io/AdZero/installation.html)

## 已验证与仍待测试

已在隔离模拟环境覆盖四目标选择、镜像/版本/ABI 拒绝、安装/卸载与 Beta.1 标记恢复；发布资产通过原厂 SDK 原始 APK SHA-256 与测试包哈希校验。**未在所有真实设备上完成 LAN DNS、代理共存、重启和断网恢复认证**。保留 Beta.1 原发行资产，Beta.2 不加入稳定版的 `sdk_verified` 和普通 LuCI 更新通道。
