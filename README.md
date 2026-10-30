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
- **兼容常用代理**：识别 NaiLink 的 dae／sing-box／mihomo，适配 PassWall、PassWall2、OpenClash、Nikki 等；各插件的 DNS 能力分别确认，保留原有代理设置。

> **注意**：DNS 过滤不是浏览器广告扩展。同域名视频广告、App 自带加密 DNS 或绕过路由器的流量，不一定能拦截。页面统计也不等于网页广告拦截率。

## 一键安装

**OpenWrt、ImmortalWrt、iStoreOS 使用同一个正式版本、同一条命令。** 以 root 登录路由器 SSH：

```sh
wget -O /tmp/adzero-install-auto.sh https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

选择「一键安装 / 自动升级」即可，无须选择固件渠道、CPU 型号或测试版。安装器自动使用本机原生的 **OPKG/IPK** 或 **APK**，检查依赖、校验下载文件，并备份原配置。

| 固件 | 安装方式 |
| --- | --- |
| OpenWrt | 同一安装入口，依赖使用本机原有软件源 |
| ImmortalWrt | 同一安装入口，依赖使用本机原有软件源 |
| iStoreOS | 同一安装入口；原厂源缺少的依赖按固件版本、修订号与 ABI 自动补齐 |

推荐带 LuCI 的 24.10 / 25.12 系列。插件本体是脚本与网页资源，共享一份 IPK 和一份 APK；原生依赖仍按本机固件匹配，不能跨固件强装。依赖缺失或存在系统包替换冲突会在停止旧保护前中止。[查看兼容范围](https://slobys.github.io/AdZero/compatibility.html)。

**首次安装保持保护关闭，升级沿用原开关。** 装好后再到 LuCI 开启过滤。旧测试版可以从同一入口升级，不再单独发布 ARM64、iStoreOS 或 Beta 版本；历史下载链接保留。

## 装好以后怎么用？

1. 打开路由器 LuCI → **服务 → AdZero**。
2. 在「过滤规则」选择列表，点击 **应用并重新加载**。
3. 回到「运行概览」开启保护，用电脑进行 **效果检测**。

网站打不开？先临时暂停，再检查是否误拦；不要直接删除代理配置或恢复记录。具体操作见 [第一次使用](https://slobys.github.io/AdZero/quick-start.html) 和 [常见问题](https://slobys.github.io/AdZero/troubleshooting.html)。

## 文档与反馈

**[完整在线文档](https://slobys.github.io/AdZero/)** · [支持固件与安装渠道](https://slobys.github.io/AdZero/compatibility.html) · [GitHub Releases](https://github.com/slobys/AdZero/releases) · [提交问题](https://github.com/slobys/AdZero/issues)

[YouTube 频道](https://www.youtube.com/@naiyou) · [Telegram 群组](https://t.me/naiyous)

项目采用 [MIT 许可证](LICENSE)。各依赖、代理插件及规则来源遵循其各自的许可。
