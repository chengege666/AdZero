# AdZero · 一键广告域名过滤

面向软路由的原生 LuCI 插件，无独立后台和二次登录。复用 adblock-fast 处理规则，把同一份有效规则接入当前代理的 DNS 链路。

**v0.6.3 是公开测试版。** 本轮修复 Argon 顶栏装饰与标题/检测按钮的重叠，移除首页的代理兼容和设备诊断区。保留 v0.6.2 的异步状态读取、轻量环境检测，以及既有操作锁、恢复机制与四种代理适配。安装矩阵覆盖 OpenWrt **24.10.8 x86/64（IPK）、25.12.5 x86/64（APK）和 25.12.5 rockchip/armv8（APK）**，各目标使用对应官方 SDK。用户已反馈 v0.5.3 在 Rockchip 真机启用成功并完成 NaiLink 配置同步；实际 LAN 过滤效果及其他设备组合仍待验收。

菜单名称统一为 **AdZero**。首屏提供状态与保护开关、规则域名、当前接入和终端验证；规则更新与接入检查并排，不展示固件、CPU、未启用代理等明细；必要的失败原因与恢复操作仍会显示。页面先显示，取得真实状态前禁用操作。支持手机、深色外观、键盘操作、等待反馈和失败重试。未采集的拦截次数不会显示为统计。设计与预览说明见 [UI_DESIGN.md](docs/UI_DESIGN.md)。

![AdZero v0.6.3 本地界面预览，使用隔离的状态快照](docs/images/adzero-v0.6.3-desktop.jpg)

## 一键安装

在匹配上述固件版本与 target 的路由器上，以 root SSH 执行：

~~~sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.6.3/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh
~~~

安装器核对固件版本、target、包管理器、软件包架构及 SHA-256；备份 /etc/config，安装依赖，然后启用保护。未列入发行清单的固件或架构会停止安装。HTTPS 方式需要 curl，也可下载 [测试发行包](https://github.com/slobys/AdZero/releases/tag/v0.6.3)，解压后执行：

~~~sh
sh install.sh --local-dir "$(pwd)"
~~~

加 --no-enable 可只安装，之后在「服务 → AdZero」开启。**已有版本可使用 --upgrade：先校验安装包、备份配置及恢复记录，再调用旧版关闭、安装并重新开启。**

~~~sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.6.3/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh --upgrade
~~~

升级后刷新 LuCI 页面；旧资源缓存未更新时可用 Ctrl+F5 强制刷新。

旧版短暂占锁时，升级器最多等待 30 秒重试；只重试旧版明确的“另一项操作正在进行”提示，其他恢复失败立即停止。锁持续占用则停止安装并保留配置、锁和恢复记录。请先提供 `ls -la /tmp/adzero.lock` 与 `ps w | grep -E '[a]dzero/(ctl|watch|adapter|backend)'` 的只读结果，不要直接删除锁。升级备份中的 state.tar.gz 可能含原有 DNS 配置，请仅保留在路由器本地。

rockchip/armv8 的固件/SDK 架构名为 aarch64_generic；APK 的 --print-arch 可能返回 CPU 名 aarch64。安装器只对已列入矩阵的该目标接受这组明确别名，仍严格匹配固件、target 和包类型。旧版 v0.5.0 只提供 x86；遇到 target 不支持时请使用上面的 v0.6.3 地址。

v0.5.3 已修正「规则已加载成功却被判失败回滚」；v0.5.2 已修正旧默认规则源；v0.6.0 已解决 LuCI 将 disabled=false 写为实际禁用属性的问题。缺少 gawk、GNU grep/sed、coreutils-sort 仍为后端推荐提示，本版未因此新增依赖。

安装依赖使用固件自己的软件源，不升级整套固件。依赖下载需要联网；离线发行包没有捆绑所有依赖。当前 APK 为开发者未签名包，安装器只对通过 SHA-256 检查的本地 APK 使用 --allow-untrusted。SHA-256 防止文件损坏，下载可信度依赖 GitHub HTTPS。

## 已实现的适配

| 代理 | 原生接入点 | 当前验证 |
| --- | --- | --- |
| NaiLink / daed | 通过 LuCI CGI/GraphQL 给当前 DNS 的 request 路由增加自有 reject 规则；在 /etc/daed 保存 GeoSite DAT | dae 解析/DAT 通过；用户反馈 v0.5.3 Rockchip 真机启用及 API 配置同步成功，LAN/eBPF 过滤效果待测 |
| PassWall | /etc/passwall/rules/block_host 的自有标记区块，以及 use_block_list | 实际 ucode/UCI 的应用、恢复和失败回滚检查；真机待测 |
| OpenClash | 官方 custom_overwrite 钩子；仅修改生成的运行配置，调用 Meta 内核检查 | 实际 Ruby YAML/锚点处理通过，Mihomo DNS 实测通过；真机待测 |
| Nikki | 原生 mixin.yaml、mixin 开关及必要的 Fake-IP 列表合并 | 实际 yq/UCI 混入与恢复通过，Mihomo DNS 实测通过；真机待测 |

Mihomo 在普通和 Fake-IP 模式下的 UDP/TCP、A/AAAA 共 8 组本机查询通过：被测广告域名返回 NXDOMAIN，正常域名保持可用。测试使用真实 v1.19.32 内核与隔离的本地 DNS 上游，不经过家庭网络。Nikki/OpenClash 的不同内核版本仍需要分别验收。

多代理同时开启、未知代理内核、Nikki core_only、现有禁用但非空的 Nikki 混入、Fake-IP 白名单模式，以及无法等价保留的放行例外会拒绝自动修改。PassWall 2 目前只识别，不自动适配。

## 工作方式和恢复

- 无可用拦截源时准备 HaGeZi Light；已有规则优先使用。适配器只读取 adblock-fast 已处理、非空的域名规则，不另行下载另一套规则。
- 使用原生扩展入口，不添加 DNS 服务器，不改 DHCP、DNS 监听端口或自行添加防火墙劫持。代理原有的 DNS/防火墙行为保持由代理管理。
- 开启会保存并临时设置 force_dns=0 和严格 HTTPS 证书验证，关闭时恢复未被外部改变的选项。
- 开启、更新可能重启当前 DNS/代理服务，短暂影响连接。只有一个启用或运行中的受支持代理才自动接入。
- /etc/adzero/adapter.json 保存恢复日志，权限 0600，可能含原有 DNS 配置，应保留在路由器上。重复同步且内容不变时不重启代理、不反复写配置。
- 启动/更新失败会尝试恢复；恢复失败保留记录并报告异常。用户修改的列表区块会保留；混入等配置存在并发修改时拒绝覆盖，等待检查。
- procd 任务每 60 秒检查规则更新及代理切换。关闭或卸载先恢复自有入口，再停止自管后端。不要手动删除恢复日志。
- 手动操作遇到锁默认等待最多 30 秒；后台同步遇到占用安静跳过。新锁以 owner 文件记录 PID 和动作，退出时只释放自己的锁；不会按超时或 PID 是否存在自动清除遗留锁。
- 状态输出包含只读 backend 检查结果；旧的 statusSuccess 或仅有 UCI 开关不会被当作当前后端正常。规则下载后由后端写入的数字 size 元数据不算用户修改，关闭时可清理本次自建且未改动的默认源。

~~~sh
/usr/libexec/adzero/ctl status
/usr/libexec/adzero/ctl enable
/usr/libexec/adzero/ctl refresh
/usr/libexec/adzero/ctl disable
~~~

界面显示「配置完成、终端待验证」，没有虚构拦截次数。AdGuard Home 运行或 adblock-fast 已由其他工具管理时，拒绝接管。

## 开发与验证

路由器端使用 BusyBox shell、ucode、现有代理自身的 Ruby/yq，不捆绑代理内核，不新增大型常驻引擎。依赖为 luci-base、adblock-fast、rpcd-mod-file、ca-bundle 和 ucode 的 fs/uci/ubus 模块。

~~~sh
sh scripts/check.sh
python3 scripts/check_openwrt_runtime.py
# 以下三项需要 ADZERO_UCODE 指向真实 ucode 命令（含 -L 模块目录）
python3 scripts/check_dns_core.py
python3 scripts/check_dae.py
python3 scripts/check_rule_source.py
# 指定 ADZERO_TEST_SHELL 可用真实 OpenWrt ash 复现上游钩子返回值
python3 scripts/check_backend_hooks.py
~~~

[功能评估与建议](docs/FEATURE_REVIEW.md) · [验证记录](docs/LOCAL_VALIDATION.md) · [DNS 适配设计](docs/DNS_ADAPTERS.md) · [SDK 构建](docs/PACKAGING.md) · [兼容矩阵](docs/COMPATIBILITY.md) · [设备验收](docs/DEVICE_ACCEPTANCE.md)

[GitHub Actions](https://github.com/slobys/AdZero/actions) 提供隔离测试及上述三个官方 SDK 组合的真实构建。离线 build_ipk.py 仅用于归档检查，不用于公开安装清单。WebCodex 源码导入记录见 [SOURCE_IMPORT.md](docs/SOURCE_IMPORT.md)。

check_rule_source.py 每次通过严格 HTTPS 下载包内配置的默认规则，用生产 ucode 解析器和固定版本 adblock-fast 的域名过滤表达式校验，避免只测模拟后端而遗漏失效链接。该检查不启动 DNS 服务、不修改 UCI；它证明开发/CI 网络当时可下载，仍需路由器自身网络验收。

## 后续兼容范围

ImmortalWrt、iStoreOS、其他 ARM 目标，以及 MIPS、RISC-V 等依照 [机器可读矩阵](docs/compatibility-matrix.json) 逐项推进。即使 LuCI 包声明 all，也不代表依赖和固件 ABI 通用；安装器不会仅凭 CPU 位数跨固件装包。

DNS 过滤无法可靠去除同域视频广告或网页占位。终端自行使用 DoH/DoT、外部 DNS 或绕过路由器的流量可能不受保护。下一步以实际设备上的启停、重启、订阅更新、IPv4/IPv6 和 LAN 查询证据决定稳定版范围。

源码使用 MIT 许可证；adblock-fast、代理插件与规则源保留各自许可。
