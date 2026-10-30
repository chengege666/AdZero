# 构建与正式发布

从 v0.22.0 开始，只发布一个 `vX.Y.Z` 正式版本。OpenWrt、ImmortalWrt、iStoreOS 共用同一插件本体：一份 all IPK、一份 noarch APK。不再创建品牌、ARM64 或 Beta 标签。

## 构建来源

使用 `scripts/fetch_sdk.py` 的官方 SDK SHA-256 固定值和 `scripts/build_sdk.py` 构建 IPK、APK，分别保留 `build-manifest.json`。构建报告必须来自当前 `luci-app-adzero` 源码哈希，记录真实 SDK 来源；不能用 `build_ipk.py` 的预览包替代 SDK 产物。

官方及厂商 SDK CI 继续验证不同固件的构建环境，但不因此向用户发布多个版本。共享包的真实元数据必须是 `Architecture: all` 或 `arch: noarch`，不能给 CPU 专用包改名冒充通用。

## 唯一的新版本打包入口

使用 `scripts/build_unified_release.py`，传入 IPK 与 APK 的 `--manifest`、`--apk-tool`、`--dependencies` 目录和 `--output` 目录。该工具验证源码、SDK 报告、实际包摘要、架构、文件内容与模式，以及 SDK 压缩后的 UI 回归。

原厂依赖来源固定在 `DEPENDENCY_ORIGINS`：先验证历史公开资产的 GitHub SHA-256，再验证内层包摘要；只复用匹配 ABI 的原生依赖，不复用其中的旧 AdZero。IPK 七个、APK 六个缺失组件按原固件构建保留，统一装入 `adzero-dependencies.tar.gz`。

发行资产包括：

- `install.sh`：所有平台使用同一个安装器。
- 两份通用应用包及 `releases.tsv`。
- 原厂依赖归档与 `dependencies.tsv`；精确按品牌、版本、修订号、target、ABI、格式匹配。
- `build-provenance.json`、`SHA256SUMS`、`INSTALL.txt`。

`scripts/install-auto.sh` 只下载并校验同一个正式 `install.sh`。发布前同步 `INSTALL_SHA256`，测试会阻止入口与实际安装器漂移。首次安装保持关闭，升级沿用旧开关；不能删掉恢复记录、绕过依赖或强制替换系统包来获得“安装成功”。

## 发布顺序

冻结源码，完成本地回归、原生依赖预检、SDK 构建及 GitHub CI，再创建普通 `vX.Y.Z` 标签。发布时设置 `prerelease=false` 和 latest，核对服务器实际资产摘要。主分支入口及文档随后指向这个已存在的正式版本。在线更新仅接受正式数字版本和带 GitHub SHA-256 的安装器资产。

旧 `build_release.py`、品牌专用构建脚本、标签与证据保留用于历史回归和恢复，不作为新版本发布入口。`docs/compatibility-matrix.json` 中旧 SDK 行是历史构建证据；当前安装选择策略位于 `unified_install`，不再要求每个固件小版本另发插件。

SDK 编译、软件包元数据与依赖求解、隔离功能测试、真实设备验收分别陈述，不能互相替代。在线路由器保持只读，除非另获实际部署授权。
