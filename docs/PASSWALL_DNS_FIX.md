# PassWall DNS 修复（v0.15.6）

本版处理交接报告中能够由 AdZero 源码与隔离实验确认的问题。未连接或修改用户路由器。

| 问题 | 本版处理 |
| --- | --- |
| 开自动分流时把 ChinaDNS-NG 改成 dnsmasq | 保留原生引擎；旧版改写且仍由 AdZero 持有的值按记录恢复 |
| DNS 进程继承 SIGCHLD 阻塞，TCP 子进程无法回收 | PassWall 启停改用外部限时工具；服务使用正常权限掩码 |
| 改了屏蔽源列表，ChinaDNS-NG 仍用旧缓存 | 仅失效该屏蔽名单缓存，由 PassWall 原生生成 |
| 编辑 DNS／分流时先退出再重新接入，重复重载 | 保留广告接入，成功时只重载一次；异常仍回退 |
| 规则存在但 DNS 进程异常仍被看成正常 | 增加信号阻塞检测，并核对原生 DNS 与屏蔽组链路 |

广告过滤仍沿 PassWall 原生 `block_host` 接入，保留节点。只有开启 AdZero 自动分流时才应用这里保存的国内、国外 DNS 和分流偏好；不强制转换未知引擎。小型 `coreutils-timeout` 为新安装依赖，准备失败时保留旧版保护。

## 依据与验证

固件对应的 [ucode 源码](https://raw.githubusercontent.com/jow-/ucode/85922056/lib.c) 在带超时的 system 路径中先阻塞 SIGCHLD 再派生进程，子进程执行前没有恢复该掩码。原生隔离实验复现了 DNS TCP 工作进程耗尽；新调用保留外部期限，五轮操作没有复现阻塞或僵尸。

[PassWall 26.10.4 的原生生成器](https://raw.githubusercontent.com/Openwrt-Passwall/openwrt-passwall/26.10.4-1/luci-app-passwall/root/usr/share/passwall/helper_chinadns_add.lua) 已支持 ChinaDNS-NG 的 null 屏蔽组及独立用户列表缓存，本版复用该接口。实际 DNS 二进制、生成器、UCI 和 rc.common 参与实验；服务主体、节点 API、DNS 上游为测试替身。详见 [验证记录](LOCAL_VALIDATION.md) 和 [原始证据](evidence/v0.15.6/)。

## 升级后简单验收

1. 升级并开启 AdZero，等待同步完成，确认「当前接入」为 PassWall。原本使用 ChinaDNS-NG 的设备，PassWall 中应仍是该引擎。
2. 在原来故障的电脑测试普通域名与被规则命中的广告域名，确认普通解析正常、广告被拦截，计数继续增加。
3. 连续访问 ChatGPT／Codex，随后测试一次 DNS 或分流编辑。确认应用后网络正常，无需反复刷新页面或重复点击应用。
4. 如仍异常，保留时间点及 `/usr/libexec/adzero/ctl status` 输出，区分 DNS 进程异常、入口未就绪和终端缓存；不要删锁、删恢复记录或清全网连接。

本版没有新增代理切换期间的临时 DNS 服务。原生重载仍可能短暂中断，电脑里已缓存的错误答案也无法由路由器远程撤销。「以后切换都不用清缓存」仍需在原电脑验收，不能由隔离测试保证。

报告中的 nftset ENOENT 在开发内核的新命名空间没有复现，尚未确定现场原因。本版不删除 nftables 表或强制重建 PassWall 规则，也不把这一项写成已修复。
