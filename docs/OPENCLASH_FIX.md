# OpenClash 开启失败修复（v0.14.1）

用户的只读输出确认：OpenClash 是唯一活动代理；AdZero 开启失败，日志为 `OpenClash did not confirm its generated DNS configuration`，随后恢复原配置、关闭保护。

## 原因与修改

- 原生启动把 `/tmp/<配置名>.yaml` 交给自定义覆写脚本，AdZero 原来只接受 `/etc/openclash/`，因此拒绝了正确的临时文件。现在严格按当前选中配置的文件名接受临时文件与生成文件，拒绝任意路径、目录穿越与符号链接。
- 仅广告 provider 改变时，OpenClash 的快速启动清单可能没有变化，导致跳过生成钩子。需要重载或恢复时使该临时清单失效；未变化的周期检查继续复用，不重复重载。
- 原生启动会隐藏钩子错误。现在保留只含固定原因的本次回执，及时返回具体失败原因，并检查后续覆写完成后的最终配置，避免仅凭服务返回零就宣称成功。
- 原来 YAML 读取依赖额外的 `ruby-json`。现在只使用 OpenClash 已依赖的 `ruby-yaml`，无需新增路由器依赖。
- 统计未启动或短暂不可读时，清空对应提示区域，修复页面显示字面量 `null`。

参考的原生源码固定在 [OpenClash 提交 e553e82](https://github.com/vernesong/OpenClash/blob/e553e82e01c697aefbe1555261a503f425e00ccd/luci-app-openclash/root/etc/init.d/openclash)，下载文件的 Git blob 校验为 `7bc7e7568c74c197668ddf6372c7013de2baf152`。

## 验证边界

新增回归覆盖：临时配置路径、原样恢复、规则变更后的快速启动、无变化不重载、被隐藏的内核错误、DNS 关闭、外部覆写移除规则、非法路径与符号链接，以及没有 ruby-json 的环境。

`scripts/check_openclash_runtime.py` 在隔离网络与 OpenWrt rootfs 中，使用真实 rc.common、提取的原生快速启动/钩子调用阶段、OpenWrt Ruby 包和真实 Mihomo，检查 Fake-IP/Redir-Host、UDP/TCP、A/AAAA、启用/增删规则/关闭恢复。该检查不运行 OpenClash 完整防火墙或真实代理节点。

浏览器检查使用生产视图、原生 LuCI DOM/Poll 和模拟 RPC，覆盖初始统计不可用、统计中断后恢复以及桌面/手机布局。完整检查结果与 SDK 包校验见 [v0.14.1 证据目录](evidence/v0.14.1/)。

本轮没有连接或修改用户路由器。升级后的设备验收：开启 AdZero 后，在电脑执行 `nslookup -type=A doubleclick.net 192.168.2.1` 和 `nslookup -type=A www.baidu.com 192.168.2.1`；前者应被拦截，后者应正常解析，并观察新增拦截应答是否计数。
