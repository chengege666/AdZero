# v0.20.0：NaiLink 与 OpenClash 别名过滤

将可选的 CNAME、HTTPS/SVCB AliasMode 和设备附加过滤适配到 NaiLink 与 OpenClash。开启「DNS 增强 → 增强 DNS 入口」及别名过滤后保存；当前唯一活动代理确认就绪后自动接入。默认关闭，不扩大订阅规则，也不改代理节点。

- NaiLink 使用原生 API 和原生 DNS 监听，保留上游、分流与缓存；增强进程正常退出或崩溃恢复后回到同一个原生解析器。已有自定义监听或不支持的内核不覆盖原配置。
- OpenClash 保留 Fake-IP。使用现有认证的本机原生真实解析接口核对别名，干净请求返回原 Fake-IP 应答。接口异常、超时或不能重现的问题上下文保留原生应答，并显示近期未完成提示；不把失败当作拦截。
- 代理切换采用两次五秒稳定采样，防止启动重叠时来回适配；启动清除旧租约，避免新进程误用旧代理地址。实际重载另需时间。
- 别名链只检查当前问题可达的应答记录，保留全局与设备放行边界。合成阻断应答不带 DNSSEC AD，不增加共享 DNS 缓存。

严格模式、OpenClash TUN、Nikki、未知 ACL、多代理及 IPv6/独立 DoH 路径保留现有边界。不是全网广告拦截或 DNS 防绕过的完整保证。首次 Fake-IP 别名核对需等待真实解析，原生解析接口异常时优先保持网络可用。

隔离验证使用实际 OpenWrt ucode/socket、nft、conntrack、dae/eBPF 和 Mihomo/Fake-IP，检查 UDP/TCP、CNAME、HTTPS/SVCB、放行、设备隔离及退出/崩溃回退。548 项全量 Python 测试及两项追加事务测试、344 项界面断言、五项文档测试、三种官方 SDK 构建和六组安装器交付检查通过。真实 NaiLink 0.6.30 API 接受新监听与窄范围路由语法，正常域名的原生 Fake-IP 映射保持一致。完整结果见 [验证摘要](evidence/v0.20.0/summary.json) 和 [增强入口验证](evidence/v0.20.0/enhance-proof.json)。

主要修改文件：`adapter.uc` 管理原生配置和恢复事务；`dns-native-lib.uc`、`dns-native.uc` 提供原生桥接与精确清理；`dns-alias-http.uc`、`dns-relay.uc` 负责有界别名核对及应答；`dns-enhance.uc`、`watch` 处理租约和稳定切换；`overview.js` 显示代理名称与近期核对异常。测试、包清单和在线文档同步更新。

未连接或修改用户路由器；隔离用例不能代替家庭网络、固件版本和浏览器完整验收。没有新增运行依赖。
