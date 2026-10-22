# OpenClash 配置校验环境修复（v0.14.3）

## 已确认并修正

用户提供的设备检查报告表明：广告后端已成功生成 246,925 条规则，失败发生在 OpenClash 的配置校验。正常服务通过 procd 设置 `SAFE_PATHS=/usr/share/openclash:/etc/ssl`，AdZero 直接调用 `clash_meta -t` 时遗漏该变量，导致合法的 `external-ui: /usr/share/openclash/ui` 被拒绝。

已对照固定提交的 [OpenClash 原生 init](https://github.com/vernesong/OpenClash/blob/e553e82e01c697aefbe1555261a503f425e00ccd/luci-app-openclash/root/etc/init.d/openclash#L863) 核实。`adapter.uc` 现在只为校验子进程设置相同的两个目录，覆盖继承值；不使用 `/`，不关闭路径检查，不复制服务密钥或改动原生启动脚本。保留原有校验、失败回滚与恢复记录。

隔离 OpenWrt rootfs 中，真实 Mihomo v1.19.32 对同一份配置：缺少变量时拒绝，带原生白名单时通过。启用、更新、关闭恢复均使用外部 UI 目录和中文/Emoji 策略组名，覆盖 Redir-Host/Fake-IP、UDP/TCP、A/AAAA。继承 `SAFE_PATHS=/` 时，适配器仍拒绝 `/tmp/untrusted-ui` 并恢复原配置。没有连接用户路由器，也没有验证其透明代理或公网节点。

## OpenClash 的 DNS 问题须单独修复

用户报告的历史日志显示，`chatgpt.com` 解析为错误地址，命中 `GeoIP(cn)` 后直连超时。这与配置校验失败是两条故障链；修正校验不等于 Google、ChatGPT 等公网服务已恢复。

修复顺序：

1. 保留当前可用 NaiLink 和原配置备份。先安装本版，按需使用安装器的 `--upgrade --no-enable`，不立即启用 AdZero。
2. 在 OpenClash 原生持久配置/覆写入口调整 DNS。受影响域名应使用经过可用代理的可信 DNS；节点域名使用独立、可直连的引导 DNS，避免建立代理前必须先通过代理解析节点的循环依赖。具体策略组名必须来自实际配置，不能猜测。
3. 核对相关域名路由规则位于 `GEOIP,CN,DIRECT` 前，指向已验证的代理组；合并已有域名策略，不覆盖用户的国内、局域网、节点规则。不要只把明文 UDP 换成另一组明文地址，也不要仅以 DNS 的 NOERROR 判断正确。
4. 在受控切换时分别验收路由器本机与 LAN：普通域名、广告域名、Google/YouTube/ChatGPT 的 A/AAAA 及实际 HTTPS。Fake-IP 的合成地址不能当作污染；HTTP 403 仅说明链路到达，不代表登录/API 成功。实际代理组不得选成 DIRECT。

语义依据：[Mihomo DNS 文档](https://wiki.metacubex.one/config/dns/) 中的 `nameserver-policy`、DNS 指定代理与 `proxy-server-nameserver`。本版没有自动加入网站专属代理规则或更换用户 DNS。

## 停用后的 dnsmasq 残留

上游 adblock-fast 1.2.4-r4 的 `stop()` 将运行规则移入缓存后重启解析器，未必移除 `serversfile` 引用。若原文件已不存在，可能留下缺文件日志。这不是 `core_rejected` 的原因。

用户后续只读回传已确认：`dhcp.@dnsmasq[0].serversfile` 保存着该引用，`uci changes dhcp` 为空，后端 enabled 为 0。下面的一次性操作仅适用于这个已确认场景。它会备份 DHCP 配置、移除这一项并重新加载系统 DNS，可能短暂影响 DNS 查询；不重启 NaiLink、不清空规则缓存。若状态已变化则停止，不绕过检查。

```sh
sh <<'ADZERO_CLEAN'
set -eu
key='dhcp.@dnsmasq[0].serversfile'
path='/var/run/adblock-fast/dnsmasq.servers'
[ "$(uci -q get adblock-fast.config.enabled)" = 0 ] || { echo '后端未停用，停止清理。'; exit 1; }
[ -z "$(uci changes dhcp)" ] || { echo 'DHCP 有未提交修改，停止清理。'; exit 1; }
[ ! -e "$path" ] && [ ! -L "$path" ] || { echo '规则路径仍存在，停止清理。'; exit 1; }
[ "$(uci -q get "$key")" = "$path" ] || { echo '引用已变化，无需执行此清理。'; exit 1; }
umask 077
backup=$(mktemp -d /etc/adzero-dns-backup.XXXXXX)
cp -p /etc/config/dhcp "$backup/dhcp"
uci -q delete "$key"
uci commit dhcp
if ! /etc/init.d/dnsmasq reload; then
  uci set "$key=$path"
  uci commit dhcp
  /etc/init.d/dnsmasq reload || :
  echo "DNS 重载失败，已恢复引用；备份：$backup/dhcp"
  exit 1
fi
echo "已清理过期引用；备份：$backup/dhcp"
ADZERO_CLEAN
```

不直接编辑临时生成文件，不调用会删除规则缓存的 `killcache`，不删除恢复记录。重载后应核对近期日志不再出现该缺文件错误。这不是对 adblock-fast 原生停止流程的永久修改；当前没有在用户设备执行上述清理。
