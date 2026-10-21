# v0.5.0 验证记录（2026-10-21）

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
