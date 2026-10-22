# v0.5.0 DNS 适配设计

ctl 在全局锁内调用 adapter。adapter 使用固件自己的 ucode、UCI 和 ubus。先识别唯一活动代理，读取 adblock-fast 已处理的安全域名输出；空、超限、非法内容或无法保留的放行例外会失败。不会把下载请求已发出当作规则准备完成。

## NaiLink

针对当前 NaiLink 的 daed 与 LuCI CGI gateway：创建 60 秒有效、只授予 luci-app-daed-router 写权限的本地 ubus session，核对授权后以同源 POST 调用 CGI。每次调用后销毁 session；不读取登录密码、JWT 密钥或 SQLite。开启前还须验证后端授权，HTTP 200 本身不代表 GraphQL 已通过。旧版缺少网关或本机身份失效时会停止并保留诊断。网关重载 502/504 不当作成功或立即回滚；保留未确认记录，原生服务进程身份更新且 API 可读后才允许显式恢复。详见 [响应修复记录](INTERACTION_FIXES.md)。

读取唯一选中 DNS profile，在 routing.request 前部增加自有 qname(ext:"adzero-geosite.dat:adzero") -> reject。规则通过 GraphQL parsedDns 检查，再 updateDns，run(dry:false) 应用。DAT 放入 daed 自己的 /etc/daed 搜索目录；绝对路径 ext 在真实 dae 检查中失败，因此不能使用绝对路径标签。

GeoSite 使用 RootDomain 匹配，保留原上游与其他请求/响应规则。恢复时删除自有块；选中 profile 发生变化时拒绝猜测。API 没有条件更新接口，只能写前复读检查，仍存在很短的并发窗口，需在设备验收中覆盖。

## PassWall

原生 block_host 追加带起止标记的域名，备份 use_block_list 并设为 1，然后重启 PassWall 使其原生 DNS 生成器读取列表。恢复只删除自有块，保留列表中后来增加的用户域名。ACL、直连/代理列表的优先级和各 DNS 后端需真机检查。

## 运行加载检查

v0.14.0 的服务调用保留 `/etc/rc.common` 解释器参数，修复直接 `sh init.d/name restart` 只定义函数却返回成功的问题。此修正适用于 PassWall、OpenClash、Nikki 和无代理时的 dnsmasq。PassWall 默认 dnsmasq 模式另有运行配置检查和有限重试；恢复原配置时不启动已停止的代理。

## SSR Plus+（v0.14.0）

使用原生 `/etc/ssrplus/deny.list` 标记块，读取黑白列表、Netflix 与原生域名转发列表，为命中屏蔽父域名的子域名补齐屏蔽项。保留节点、DNS 上游和原生分流，不触发 SSR Plus+ 自带广告订阅更新。当前不支持 AdZero 自动分流，开启前会明确拒绝，尚未写入配置。

原生服务重新生成 DNS 后，检查运行中的系统 dnsmasq 是否包含 `dnsmasq-ssrplus.conf`、其中指向的生成目录是否加载最多三个屏蔽样本。隔离验收使用固定提交的原生 `gfw2ipset.sh`，控制服务环境，不运行代理传输与防火墙；真实设备仍待验收。

参考：[SSR Plus+ 原生生成器](https://github.com/fw876/helloworld/blob/2abdc9aa9e19607774dc9789709212b70b8607c6/luci-app-ssr-plus/root/usr/share/shadowsocksr/gfw2ipset.sh)。

## OpenClash 原生覆写

在官方 openclash_custom_overwrite.sh 的 shebang 后插入自有调用，确保现有 exit 0 前执行。v0.14.1 修正原生钩子实际传入 `/tmp/<当前配置名>.yaml` 的路径兼容问题；只允许当前选中配置对应的临时文件或生成文件，拒绝任意路径和符号链接，订阅原文保留。v0.14.2 使用已有 ruby-yaml 安全读取，再把已解析数据转换为标准 JSON；不使用可能生成 YAML 专用转义的 Psych.to_json，也不对序列化文本做正则替换。支持中文、Emoji、控制字符和 anchors，拒绝对象标签、循环与非有限数字；无需额外 ruby-json。调用现有 clash_meta -t 检查后原子替换。

增加文件域名 provider、指向 rcode://name_error 的 nameserver-policy，以及对应 Fake-IP 排除和 REJECT 规则。AdZero 规则发生变化或关闭恢复时，使 OpenClash 自己的临时快速启动清单失效，确保重新生成；未变化的周期检查不重载。重启后核对本次钩子回执与最终生成文件，不能只以服务返回零判断成功；钩子失败记录固定原因并及时回滚，避免错误输出被原生脚本隐藏后等待到超时。运行时缺少 Meta 核心、DNS 关闭或后续自定义覆写移除规则都会失败。

## Nikki

使用 mixin.yaml 与 mixin_file_content 原生入口，以 nikki-rules 前置规则，避免替换订阅 .rules。保留有效配置中的 Fake-IP 过滤条目；若 Nikki 的 UCI 过滤数组会在最后覆盖 YAML，则把自有条目加入该数组，并记录原值。重启后检查生成配置仍含 provider、DNS policy 和过滤条目。

core_only 绕过混入，不能自动使用。禁用但有内容的混入不自动打开，避免连带启用用户保存的其他配置。用户自行编辑混入后，恢复会保留日志并停止覆盖。

## 事务与限制

/etc/adzero/adapter.json 记录原文、应用值和阶段，权限 0600。写前保存意图，临时文件与目标同目录后 rename；不完整事务不能重新覆盖。更新失败恢复到上一份规则；恢复失败显示 recovery_required 并保留记录。规则文件的二进制内容在日志中使用 Base64，防止 JSON 损坏 protobuf。

原子替换不等同于断电后文件系统耐久性保证；包安装/卸载钩子、procd 时序、DNS 缓存和真实流量仍须设备验收。自有文件保存在闪存，规则较大时需要检查空间和更新写入频率。内容不变的每分钟同步不会重启或重复写规则。

## 审阅依据（固定提交）

- [NaiLink CGI 网关与 init](https://github.com/slobys/NaiLink/tree/9dc50c58c5e844c948197b348c654c872625fb68)
- [dae-wing DNS API](https://github.com/daeuniverse/dae-wing/tree/dc503088945812c11235b35362d2bfa1a4c3bdf0/graphql/service/dns)
- [PassWall](https://github.com/Openwrt-Passwall/openwrt-passwall/tree/ae258e4da46aa34567230f55e401ced4cb7738ad)
- [OpenClash](https://github.com/vernesong/OpenClash/tree/e553e82e01c697aefbe1555261a503f425e00ccd)
- [Nikki](https://github.com/nikkinikki-org/OpenWrt-nikki/tree/78e1a751d55ed0762811f054ee699049473da7b8)
- [Mihomo DNS 配置](https://wiki.metacubex.one/config/dns/)

这些提交是适配实现的参考基线，不代表其所有历史和未来版本都已认证。
