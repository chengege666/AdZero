<p align="center">
  <img src="docs/images/adzero-logo.png" alt="AdZero" width="96" height="96">
</p>

<h1 align="center">AdZero</h1>
<p align="center">让软路由帮你拦广告，管理 DNS 更简单。</p>

<p align="center">
  <a href="https://slobys.github.io/AdZero/">📖 在线使用文档</a> ·
  <a href="https://github.com/slobys/AdZero/releases">📦 下载安装</a> ·
  <a href="https://github.com/slobys/AdZero/issues">💬 问题反馈</a>
</p>

AdZero 是一款运行在 **OpenWrt、ImmortalWrt、iStoreOS** 软路由上的广告过滤插件，直接用路由器的 **LuCI 管理页面**操作，不需要额外安装管理 App。

## 能做什么？

- **拦广告、挡追踪**：使用 adblock-fast 和过滤规则，减少广告及追踪域名请求。
- **规则管理**：添加订阅、自定义拦截与放行；网站误拦时可以临时暂停或放行。
- **看过滤效果**：查看 DNS 请求、拦截数量和响应耗时，并从电脑实际检测。
- **设置 DNS**：修改国内/国外 DNS、备用地址；分流与严格模式按需启用。
- **兼容常用代理**：适配 NaiLink、PassWall、OpenClash、Nikki 等，尽量保留原有代理设置。

> **注意**：DNS 过滤不是浏览器广告扩展。同域名视频广告、App 自带加密 DNS 或绕过路由器的流量，不一定能拦截。页面统计也不等于网页广告拦截率。

## 一键安装：自动识别固件

**不用选择安装版本或 CPU 架构。** 以 **root 身份登录软路由 SSH**，运行这一条命令：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh -o /tmp/adzero-install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

安装助手会自动检测 **OpenWrt / ImmortalWrt / iStoreOS** 的固件版本、设备 target、包架构和安装格式，再打开对应的中文菜单：

| 自动选择的渠道 | 适用范围 |
| --- | --- |
| **常规安装** | OpenWrt 24.10.8 / 25.12.5，ImmortalWrt 24.10.6 / 25.12.2 的指定目标 |
| **ARM64 公测** | OpenWrt 25.12.6、ImmortalWrt 25.12.2 的 Rockchip / MediaTek Filogic |
| **iStoreOS 公测** | iStoreOS 25.12.6（修订 2026102312）的 x86_64 / ARMSR / R6XS |
OpenWrt / ImmortalWrt ARM64 公测为 **Beta.2**；iStoreOS 已更新 **Beta.3**，修复 APK 环境误判并保留旧版安全卸载。统一安装命令会自动选择对应版本。

**正在适配（尚不能安装）：**iStoreOS **24.10.8（2026073111）** 的 x86_64、ARM64 ARMSR 和 R6XS，已完成原厂固件/依赖预检，原生 IPK 编译与安装验收待完成。[查看进度 PR #18](https://github.com/slobys/AdZero/pull/18)。

匹配不到就会**拒绝安装并说明原因**，不会强装其他架构的软件包。下载的安装脚本还会经过 SHA-256 校验。[查看完整固件兼容表](https://slobys.github.io/AdZero/compatibility.html)。

**建议首次选择「安装但不启用过滤」**，先确认 SSH、LuCI、正常上网与原有代理没问题，再手动开启。公测版仍需更多真实设备测试，请先备份配置并准备本地恢复方式。

## 装好以后怎么用？

1. 打开路由器 LuCI → **服务 → AdZero**。
2. 在「过滤规则」选择列表，点击 **应用并重新加载**。
3. 回到「运行概览」开启保护，用电脑进行 **效果检测**。

网站打不开？先临时暂停，再检查是否误拦；不要直接删除代理配置或恢复记录。具体操作见 [第一次使用](https://slobys.github.io/AdZero/quick-start.html) 和 [常见问题](https://slobys.github.io/AdZero/troubleshooting.html)。

## 文档与反馈

**[完整在线文档](https://slobys.github.io/AdZero/)** · [支持固件与安装渠道](https://slobys.github.io/AdZero/compatibility.html) · [GitHub Releases](https://github.com/slobys/AdZero/releases) · [提交问题](https://github.com/slobys/AdZero/issues)

[YouTube 频道](https://www.youtube.com/@naiyou) · [Telegram 群组](https://t.me/naiyous)

项目采用 [MIT 许可证](LICENSE)。各依赖、代理插件及规则来源遵循其各自的许可。
