# AdZero：三种固件 ARM64 适配与验收

> 开发分支上的目标均为**候选**，不意味着公开发布或实体设备已经通过。公开安装器只读取 `docs/compatibility-matrix.json` 的 `sdk_verified`，不会使用本页候选清单。

## 当前目标

| 固件 | 固件版本 / target | 进度 |
| --- | --- | --- |
| OpenWrt | 25.12.5 / rockchip/armv8 | v0.21.5 已有对应 SDK APK，真机 LAN 尚未普遍验证 |
| OpenWrt | 25.12.6 / rockchip/armv8 | 新官方 SDK SHA 固定，CI 构建候选 |
| OpenWrt | 25.12.6 / mediatek/filogic | 新官方 SDK SHA 固定，CI 构建候选 |
| ImmortalWrt | 25.12.2 / rockchip/armv8 | 独立厂商 SDK SHA 固定，CI 构建候选 |
| ImmortalWrt | 25.12.2 / mediatek/filogic | 独立厂商 SDK SHA 固定，CI 构建候选 |
| iStoreOS | 25.12.6-2026102312 / armsr/armv8 | 原厂配置/13 feeds/SHA 已核验，原生 APK 待编译和设备测试 |
| iStoreOS | 25.12.6-2026102312 / rockchip/armv8（R6XS） | 原厂配置/15 feeds/SHA 已核验，原生 APK 待编译和设备测试 |

Rockchip 的发行包架构常为 `aarch64_generic`，Filogic 为 `aarch64_cortex-a53`。即便 APK 运行环境显示 `aarch64` CPU，**也不能自动推断它与所有 ARM64 包兼容**。完整固件版本、target、包架构及发行版 ID 都要精确匹配。iStoreOS 还必须检查十位 `DISTRIB_REVISION`。

## OpenWrt / ImmortalWrt：分别构建

`scripts/fetch_sdk.py` 从**所属厂商官方目录**下载对应 target SDK，下载归档前后核对官方 sha256sums，记录 `adzero-sdk-origin.json`。 `scripts/build_sdk.py` 在改动 SDK 源码或进行编译之前校验这个来源文件中的厂商、版本、target、绝对路径和固定哈希，不能靠手填 SHA 或相同架构跨厂商构建。

Linux/WSL 示例：

```sh
# OpenWrt 25.12.6，MediaTek Filogic
python3 scripts/fetch_sdk.py --firmware openwrt --release 25.12.6 \
  --target mediatek/filogic --directory "$HOME/adzero-sdks" --cache "$HOME/adzero-cache"

# ImmortalWrt 25.12.2，Rockchip ARMv8
python3 scripts/fetch_sdk.py --firmware immortalwrt --release 25.12.2 \
  --target rockchip/armv8 --directory "$HOME/immortal-sdks" --cache "$HOME/immortal-cache"
```

在返回的 SDK 目录内，用 SDK 自带 `./scripts/feeds update base packages luci`，安装 LuCI、adblock-fast、ucode、tcpdump/conntrack 等所需 feeds；之后参照仓库 `.github/workflows/sdk.yml` 或 `.github/workflows/vendor-sdk.yml` 的完整编译、APK 内容及 LuCI 验证命令。每个目标单独生成 `build-manifest.json` 与 SHA-256。

## iStoreOS：原厂 ARM64 构建路径

官方 25.12.6、修订 2026102312 的原厂来源分别为：

- ARMSR：`https://fw20.koolcenter.com/iStoreOS/armsr/`
- Rockchip R6XS：`https://fw20.koolcenter.com/iStoreOS/r6xs/`

对每个目标的 `commit.buildinfo`、`config.buildinfo`、`feeds.buildinfo`、`feeds.conf`、`version.latest.v2` 各自固定 SHA-256，官方镜像名和压缩镜像哈希也被固定。它们对应的完整源码提交同为 `283d02639c740f8ae6e9425b48be8c61f152c6b8`，**但完整配置与 feeds 不同**，不能混用或直接使用 x86_64 原生包。

只读厂商元数据核对（不修改固件）：

```sh
python3 scripts/probe_istoreos_arm64.py --profile armsr
python3 scripts/probe_istoreos_arm64.py --profile rockchip-r6xs
```

创建全新源码目录（禁止覆盖已有构建）：

```sh
mkdir -p "$HOME/istoreos-builds"
python3 scripts/prepare_istoreos_source.py --profile rockchip-r6xs \
  --directory "$HOME/istoreos-builds/rockchip-r6xs-2026102312"
```

进入所创建的原厂 Buildroot，按照固定的 `feeds.conf` 获取并安装全部 feeds，确认源码提交未漂移，再运行：

```sh
python3 scripts/build_istoreos_native.py \
  --source "$HOME/istoreos-builds/rockchip-r6xs-2026102312" \
  --output "$HOME/istoreos-builds/new-r6xs-candidate" --jobs 4
```

它依次编译原厂 tools、toolchain、Linux target、LuCI host 和 AdZero APK，再校验 vendor 来源、target、feeds、包架构、源码、权限与导出文件 SHA。**即使编译及封装验证成功，仍只生成 `publishable=false` 的候选包**，不能直接写入公开 `releases.tsv`。

## 发布和真机验收门槛

每个目标独立检查：

1. 原厂 SDK 的**实际编译产物**、APK 声明及 ABI，与固件 `/etc/openwrt_release`、软件包管理器架构一致。
2. APK 安装、依赖预检、原有软件保留、AdZero 默认禁用、启停、卸载及异常恢复均可复现。
3. LAN 终端 IPv4/IPv6、DNS 拦截/放行、NaiLink/PassWall DNS 路径、代理共存、重启、升级与回滚实测。
4. 编译版本与发行包、`releases.tsv` 和每个 SDK/包 SHA 一致；经证据复核后才允许新增 `sdk_verified` 行并**发布新版本**。不修改旧 v0.21.5 发布资产。

所有真实设备未完成的检查必须标注为待测，不把源码核验、CI 编译或虚拟机安装冒称设备网络认证。
