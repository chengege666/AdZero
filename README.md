<p align="center">
  <img src="docs/images/adzero-logo.png" alt="AdZero Logo" width="104" height="104">
</p>
<h1 align="center">AdZero</h1>
<p align="center">软路由上的广告过滤与 DNS 分流插件</p>
<p align="center">
  <a href="https://github.com/slobys/AdZero/releases">下载安装包</a> ·
  <a href="docs/DNS_SETTINGS.md">DNS 设置说明</a> ·
  <a href="https://github.com/slobys/AdZero/issues">反馈问题</a>
</p>

AdZero 直接集成在 OpenWrt 的 LuCI 管理页面中，无需额外登录。添加想用的规则、按需调整 DNS，修改完成后统一应用。

## 能做什么

- **广告过滤**：内置常用规则库，也能添加自己的 HTTPS 规则订阅。
- **批量应用**：先添加、编辑或开关多项规则，再一次应用，减少重复加载。
- **拦截统计**：每秒自动刷新局域网可观察范围内的 DNS 拦截请求数与比例，和规则域名数量分别展示；可一键清零请求数和拦截数，从同一时刻重新计算比例。
- **最近拦截**：按需开启 5 分钟的内存记录，查看域名、次数并检查误杀。
- **效果检测**：复制页面提供的查询命令，在电脑执行后自动核对拦截与正常解析。
- **访问控制**：集中查询域名、查看最近拦截，搜索和批量管理自定义放行／拦截名单；改完统一应用。
- **临时暂停**：网站或 App 异常时，暂停几分钟做对比，到期尝试自动恢复。
- **可编辑 DNS**：国内、国外 DNS 都有默认地址，可以自行添加、删除和调整顺序。
- **可选自动分流**：有受支持代理时，国内直连、国外走当前代理；无代理时使用国内 DNS 和本地直连。默认关闭。

提供 NaiLink、PassWall、OpenClash、Nikki 的 DNS 适配，并支持 SSR Plus+ 原生域名广告过滤。使用 adblock-fast 处理广告规则，无需另外安装 AdGuard Home 或 SmartDNS。

## 安装与升级

当前为 **v0.15.2 测试版**，修复代理切换与关闭恢复后页面状态滞留的问题，自动核对完成状态，减少手动刷新。保留本地升级、统计清零和独立「访问控制」。先确认固件属于下方兼容范围，再以 root 登录路由器 SSH，执行：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.15.2/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh
```

已有 AdZero，使用升级命令：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.15.2/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh --upgrade
```

安装后打开 **服务 → AdZero**。升级后如果页面未更新，按 `Ctrl + F5` 刷新。

安装器会检查机型与软件包、备份配置并安装依赖。也可以从 [Releases](https://github.com/slobys/AdZero/releases/tag/v0.15.2) 下载对应发行包。详细操作见 [安装与恢复](docs/INSTALLATION.md)。

## 日常怎么用

1. **选规则**：在「过滤规则」添加需要的列表，也可以粘贴自己的订阅地址。
2. **按需改设置**：修改 DNS 或分流开关，选择会进入「待应用」。每组第一条 DNS 为当前地址，其余仅作备选保存，不会自动测速或切换。
3. **统一应用**：改完后点击「应用并重新加载」。平时用「重新加载」应用当前配置，用「更新订阅」获取新规则；「手动校验」只检查本地已下载规则。

「访问控制」集中管理最近拦截和自定义名单；用法及范围见 [统计与访问控制](docs/ACCESS_CONTROL.md)。

保护总开关、临时暂停为即时操作；访问控制中的放行／拦截先加入待应用，改完统一生效。应用规则或网络设置时，可能短暂重载 DNS 或当前代理；具体耗时取决于设备与规则规模。

## 兼容范围

以下组合已有对应官方 SDK 构建包：

| 固件 | 设备目标 | 软件包 |
| --- | --- | --- |
| OpenWrt 24.10.8 | x86/64 | IPK |
| OpenWrt 25.12.5 | x86/64 | APK |
| OpenWrt 25.12.5 | rockchip/armv8 | APK |

SDK 构建与隔离测试已通过，实际设备的网络与过滤效果仍需验证。ImmortalWrt、iStoreOS、其他版本与架构按 [兼容矩阵](docs/COMPATIBILITY.md) 逐步推进，安装器会拒绝尚未匹配的组合。

NaiLink、PassWall、OpenClash、Nikki 的不同版本需分别验收。SSR Plus+ 使用原生屏蔽列表，保留节点和分流设置，需关闭 AdZero 自动分流；PassWall 2 和 HomeProxy 目前仅识别。同时开启多个代理或遇到未知代理时，不会自动接管。

PassWall 的默认 dnsmasq 和 SSR Plus+ 接入会核对运行进程、配置加载路径与屏蔽规则样本。未加载时有限重试并显示提示，页面仍可操作；这不能代替终端效果检测。内容未变且运行配置正常时，不重复重启代理。

切换时先停止旧代理、启动新代理，再点击「重新检测」。NaiLink 的管理服务和代理内核分别判断；说明见 [切换代理](docs/PROXY_SWITCHING.md)。

## 卸载

先关闭保护并恢复 AdZero 管理的设置，成功后卸载。按路由器的包管理器选择一条：

```sh
# APK 固件（如 OpenWrt 25.12.5）
/usr/libexec/adzero/ctl disable && apk del luci-app-adzero

# OPKG 固件（如 OpenWrt 24.10.8）
/usr/libexec/adzero/ctl disable && opkg remove luci-app-adzero
```

如果恢复失败或提示操作锁占用，先保留错误信息，不要强制卸载或手动删除恢复记录。

## 使用前了解

DNS 过滤主要拦截广告和追踪域名，无法保证去除同域视频广告或网页空白。设备使用自己的加密 DNS、外部 DNS 或绕过路由器时，过滤可能不生效。

界面显示「已开启」表示配置已应用，实际过滤效果还需要在手机或电脑上确认。

「效果检测」通过后会显示对应设备。统计保存在内存中，重启路由器后清零；不代表网页广告个数，不保存完整查询日志。范围与操作见 [统计与检测说明](docs/OBSERVATION.md)。

[规则管理](docs/RULE_SOURCES.md) · [DNS 设置](docs/DNS_SETTINGS.md) · [AdGuard 参考与优化方向](docs/ADGUARD_REVIEW.md) · [验证记录](docs/LOCAL_VALIDATION.md) · [开发与构建](docs/PACKAGING.md) · [Logo 与设计说明](docs/BRAND.md)

源码采用 [MIT 许可证](LICENSE)。adblock-fast、代理插件与规则源遵循各自许可。
