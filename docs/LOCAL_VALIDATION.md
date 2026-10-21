# v0.5.1 验证记录（2026-10-21）

本轮针对真实回报的 OpenWrt 25.12.5 r33051-f5dae5ece4 / rockchip/armv8，补充 ARM64 官方 SDK 构建入口和安装清单。

- 官方 profiles 的 arch_packages 为 aarch64_generic；SDK 的 CONFIG_ARCH 为 aarch64，用户的 APK --print-arch 返回 aarch64。安装器为这一具体 target 增加明确别名，同时检查固件声明 ABI，保留固件版本/target/包格式边界。
- 完整回归 **109 项通过**，使用官方 OpenWrt BusyBox/ash、ucode/UCI，以及实际 Ruby/yq；其中安装器 13 项包含用户回报字段、缺失 target、错误 CPU/ABI 和跨目标清单拒绝。
- 本轮路由器包源码哈希为 `9cf5ed3294071b34655ce16d1390bf67a75d2afc7161705dd150c2558e90d9b4`。适配器运行代码未变，只更新包版本；v0.5.0 的真实 Mihomo/dae 证据保留在下方，不能当成 ARM 核心或 LAN 实测。
- x86/64 的 24.10.8 IPK、25.12.5 APK 已重新构建；rockchip/armv8 的 25.12.5 APK 也通过了独立的官方 SDK 构建。三包的 12 个运行文件内容/权限及实际 LuCI JS 检查通过。最终 manifest 和运行检查记录存入 evidence/v0.5.1。
- 尚未执行用户设备安装、NaiLink API/eBPF 或 LAN DNS 查询。用户提供设备元数据不等于设备安装通过。

ARM SDK：[官方发布目录](https://downloads.openwrt.org/releases/25.12.5/targets/rockchip/armv8/)，归档 SHA-256：

~~~text
59194a023968398af64bfa7d8bc3eac322641f6dc9cdbade28a4d9dd41866eba
~~~

以下保留 v0.5.0 的历史基线。

## v0.5.0 验证记录（2026-10-21）

本轮验证对象为路由器包目录源码 SHA-256：

~~~text
3a290df6e47fae75d8ce2aab0e893732a2925836b33c9463f7167ab64bf23501
~~~

| 验证 | 结果 | 范围 |
| --- | --- | --- |
| Python 回归 | 97 项通过 | 官方 OpenWrt BusyBox/ash、ucode/UCI；服务/包管理器和平台数据为替身 |
| LuCI | 交互模拟、语法通过 | 无真实浏览器会话/路由器 |
| Nikki | 实际 yq 合并、UCI 和恢复通过 | 本地配置与服务替身 |
| OpenClash | 实际 Ruby YAML、锚点和钩子事务通过 | 内核配置检查在该事务用例中为替身 |
| Mihomo v1.19.32 | 8 组真实 DNS 检查通过 | 本地回环网络，普通/Fake-IP × UDP/TCP × A/AAAA |
| dae v2.1.1 | 真实解析与 1002 条 GeoSite DAT 加载通过 | 不运行 eBPF 或 daed API |
| OpenWrt 24.10.8 SDK | 实际 IPK 构建通过 | x86/64，GCC 13.3 / musl |
| OpenWrt 25.12.5 SDK | 实际 APK 构建通过 | x86/64，GCC 14.3 / musl |
| SDK 包检查 | 12 个文件内容/权限及实际前端 JS 检查通过 | 解包检查，无生命周期执行 |
| 安装器 | 平台、校验、备份、拒绝/启用边界通过 | 包管理器为替身 |
| 真机/LAN/升级卸载 | 未执行 | 不能将前述结果提升为设备认证 |

原始源码导入曾核对 18 个文件；v0.4.0 的 79 项基线和原始 v0.3 开发包留在本地历史产物中。此次不是继续把模拟测试当作 SDK 构建。

## 具体修复证据

- 实际 SDK 的 scripts/config 是源码目录；改为 .config 选项 + make defconfig。
- 25.12.5 首次缺少 po2lmo，显式构建 luci-base 宿主工具后成功。
- 官方 ucode 的导出、正则和文件接口与 JavaScript/新文档存在差异；代码在真实 24.10.8 用户空间中运行，未用 Node 代替 ucode。
- 只有 nameserver-policy 时，真实 Mihomo Fake-IP 仍返回假 IP；加入匹配的 Fake-IP 过滤后，广告测试域名返回 NXDOMAIN，正常控制域名可用。
- dae 的 ext 绝对路径在真实校验中失败；改为 /etc/daed 搜索目录里的文件名后，GeoSite 加载通过。

## 安装包

| 包 | SHA-256 |
| --- | --- |
| OpenWrt 24.10.8 IPK | 00f0172a16fedb6457933aacd9552c31da822a0e3ff2c40e04fe23e3a41a661c |
| OpenWrt 25.12.5 APK | 3415e2c2f85463d69b1034c959a85fcc9004ecd092cdc0f69a8b5931f46f8f69 |

证据 JSON 位于 [evidence/v0.5.0](evidence/v0.5.0/)。源码哈希覆盖包目录相对路径及文件内容，文件执行位另由解包检查验证。开发文档和测试不计入该包哈希。

## 复现

~~~sh
python3 scripts/check_openwrt_runtime.py
export ADZERO_UCODE="$PWD/.sdk/runtime-24.10.8/libc.so --library-path $PWD/.sdk/runtime-24.10.8 $PWD/.sdk/runtime-24.10.8/ucode -L $PWD/.sdk/runtime-24.10.8"
python3 scripts/check_dns_core.py
python3 scripts/check_dae.py
~~~

完整的配置解析用例还需要开发机有 Ruby/yq。SDK 步骤见 [PACKAGING.md](PACKAGING.md)。运行库、上游测试核心与 SDK 都只放在开发缓存，不进入路由器安装包。版本和下载 SHA-256 固定在相应脚本中。

GitHub 仓库含可重跑的隔离测试和官方 SDK Actions；本页记录的是本地实际执行结果，不预先宣称 Actions 成功。
