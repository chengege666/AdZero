# AdZero v0.23.0

OpenWrt、ImmortalWrt、iStoreOS 继续使用同一个正式版本和安装入口。

- NaiLink 通过新版 coreStatus 与实际进程归属识别 dae、sing-box、mihomo，兼容旧接口。后台同步感知同一插件内的换核和实例更换。
- PassWall2 接入原生复制 dnsmasq 的广告过滤，并在重载后检查运行实例确实继承当前过滤文件。保留节点、DNS 引擎、上游和原生分流；不混用 PassWall v1 的接口。
- 共享内核按配置参数归属，排除配置校验进程、日志路径和未就绪的管理服务；状态不明时保留原配置。
- 页面显示实际 NaiLink 内核，换核尚未同步时显示待同步。PassWall2 的 DNS 设置由原插件管理，不展示为 AdZero 已改写上游。

PassWall2 暂不支持 AdZero 严格 DNS 模式；NaiLink 的可选 CNAME／设备增强监听入口目前仅适用于 dae，原生新内核不强行启用该入口。基础域名过滤和增强入口分别确认。

测试覆盖原生 ucode/UCI、真实 OpenWrt dnsmasq 的 UDP/TCP A/AAAA 查询、界面与 SDK 构建；没有在在线路由器上升级、切换或重启服务，不等于所有物理设备组合均已验收。
