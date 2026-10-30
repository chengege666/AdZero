# 安装与恢复

OpenWrt、ImmortalWrt、iStoreOS 共用同一个正式版本与安装菜单，不再按品牌、ARM64 或 Beta 分渠道。

```sh
wget -O /tmp/adzero-install-auto.sh https://raw.githubusercontent.com/slobys/AdZero/main/scripts/install-auto.sh && sh /tmp/adzero-install-auto.sh --menu
```

选择 1 自动安装或升级，选择 3 预检，选择 4 安全卸载。首次安装不开启保护，升级保留原开关；配置备份位于 `/etc/adzero-backups/`。

本体共享 IPK/APK，原生依赖按本机固件匹配。安装前核对原生软件包清单、摘要与依赖计划；不跨固件强装，不替换已有 tcpdump，不更换其他系统包。iStoreOS 原厂缺失依赖按精确版本、修订号、target 和 ABI 自动补齐。真实配置冲突、未恢复的所有权记录和操作锁保护仍保留。

完整操作、预检边界、旧版迁移与卸载说明以[在线安装文档](https://slobys.github.io/AdZero/installation.html)为准；支持范围见[兼容说明](https://slobys.github.io/AdZero/compatibility.html)。历史发布链接保留供恢复，不再要求用户选择专用测试版。
