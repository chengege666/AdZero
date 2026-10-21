# v0.6.3 构建、安装与发行

公开安装只使用真实 SDK 输出，不使用 build_ipk.py 的离线预览。

| 官方 SDK | target | 格式 | 当前结果 |
| --- | --- | --- | --- |
| OpenWrt 24.10.8 / GCC 13.3 | x86/64 | IPK | 实际构建通过 |
| OpenWrt 25.12.5 / GCC 14.3 | x86/64 | APK | 实际构建通过 |
| OpenWrt 25.12.5 / GCC 14.3 | rockchip/armv8 | APK | 实际构建通过 |

SDK 的 SHA-256 固定在 scripts/fetch_sdk.py，来源为对应 [官方版本目录](https://downloads.openwrt.org/releases/)。构建保留 SDK 自带 feeds.conf.default；不能用另一固件的 feeds 代替。

## Linux / WSL 复现

需要 make、gcc/g++、ncurses 开发头文件、git、gawk、rsync、file、unzip、zstd、Python 3 和 Node。SDK 放在 Linux 文件系统，避免 Windows 挂载目录的大小写与权限差异。

~~~sh
python3 scripts/fetch_sdk.py --release 24.10.8 --directory "$HOME/adzero-sdks" --cache "$HOME/adzero-sdk-cache"
~~~

进入返回的 SDK 目录，准备它自己的 feed：

~~~sh
./scripts/feeds update base packages luci
./scripts/feeds install luci-base adblock-fast rpcd-mod-file ca-bundle ucode-mod-fs ucode-mod-uci ucode-mod-ubus
~~~

回到本项目，使用 fetch 输出的 sdk 路径和 sha256：

~~~sh
python3 scripts/build_sdk.py --sdk /absolute/path/to/sdk \
  --firmware openwrt --release 24.10.8 --target x86/64 \
  --format ipk --sdk-sha256 ac4a0405d2eea821b06f93c14ba13ffa90ad0457648903df7dde02570027ab21 \
  --output dist/v0.6.3/openwrt-24.10.8
~~~

25.12.5 使用对应 SDK、--format apk 和 SHA-256：

~~~text
0c8df0151a1e88feb7c03d694d61f6a18d51872815b7c811d76e2b77504d5e9c
~~~

入口写入 .config 的包选项并 make defconfig，先构建 luci-base 的宿主工具，再编译 AdZero。OpenWrt 的 scripts/config 是 Kconfig 源码目录，不是可执行配置 CLI。显式构建宿主工具解决了 25.12.5 首次构建缺少 po2lmo 的问题。

构建器只同步自己曾复制且未被手动改动的包目录；其他已有源码不覆盖。源文件被删除时要求新 SDK，以避免旧文件残留。构建前后校验源码哈希，检测实际 target、架构及包格式；没有真实输出就失败。

Rockchip 使用 --target rockchip/armv8 下载独立 SDK，SHA-256 为：

~~~text
59194a023968398af64bfa7d8bc3eac322641f6dc9cdbade28a4d9dd41866eba
~~~

构建时指定 --target rockchip/armv8 --format apk。官方 SDK 的 CONFIG_TARGET_ARCH_PACKAGES=aarch64_generic、CONFIG_ARCH=aarch64，与 APK --print-arch 的 CPU 名分别记录，不混为同一个字段。源码/格式检查和发布清单仍以实际 SDK target/ABI 为准。

## 检查真实包

~~~sh
python3 scripts/check_sdk_packages.py dist/v0.6.3/openwrt-24.10.8-x86/luci-app-adzero_0.6.3-r1_all.ipk
python3 scripts/check_sdk_packages.py dist/v0.6.3/openwrt-25.12.5-x86/luci-app-adzero-0.6.3-r1.apk --apk-tool /absolute/sdk/staging_dir/host/bin/apk
~~~

检查 17 个源文件（含界面 CSS 和图标许可）的存在、运行代码内容和权限（含 backend/backend.uc 和 probe/probe.uc），并对 SDK 实际压缩后的 LuCI JS 执行语法及 54 项交互断言。CSS 保留原文，避免旧 SDK 压缩工具破坏自定义属性。仅解包，不执行安装钩子。官方 IPK 使用 gzip tar 外层；APK 使用真正的 apk-tools 读取，不能改扩展名转换。

脚本 ctl、probe、adapter、backend、watch 和 init.d/adzero 为 0755；ucode 源码、规则库、配置和前端资源为 0644。SDK 另外生成自身的包管理元数据与生命周期脚本。

## 发行目录

~~~sh
python3 scripts/build_release.py \
  --manifest dist/v0.6.3/openwrt-24.10.8-x86/build-manifest.json \
  --manifest dist/v0.6.3/openwrt-25.12.5-x86/build-manifest.json \
  --manifest dist/v0.6.3/openwrt-25.12.5-rockchip/build-manifest.json
~~~

发行目录包含 install.sh、三个实际 SDK 包、releases.tsv 和 build-provenance.json。它拒绝不属于当前源码哈希的构建。GitHub Release v0.6.3 标记为 prerelease；一键命令固定到同一个版本，避免安装脚本与包混用。

安装器先检查平台和 SHA-256，保存 /etc/config 备份，再使用固件的软件源补齐依赖。APK 自有包尚未签名，仅该本地文件通过 --allow-untrusted 安装；没有关闭 HTTPS 验证，也不使用强制覆盖或强制架构。安装失败时不自动删除已有包或整个配置目录。

不能把源码 all/noarch 视为跨固件保证。其他厂商、24.10 的其他补丁版本和 CPU 架构，须先补齐对应 SDK 和设备证据，才能写入安装清单。配置包的 SDK 成功仍不等于设备生命周期和终端 DNS 验收成功。

## 开发预览

python3 scripts/build_ipk.py 仍能生成可重复的离线 OPKG 归档，供测试路径和权限。它不进入公开安装清单。正式发行来源与测试证据见 [LOCAL_VALIDATION.md](LOCAL_VALIDATION.md)。
