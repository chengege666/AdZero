# OpenClash 启动顺序与字符转换修复（v0.14.2）

用户在 0.14.1 回传：先启动 OpenClash 再开启 AdZero 会失败，反向顺序看似成功；Google 无法访问，ChatGPT 可以打开。状态中 OpenClash 是唯一活动代理，广告后端已载入规则，但代理适配为 inactive，状态 inconsistent。后台日志连续出现 `Failed to parse JSON string: invalid string sequence` 和钩子失败。

## 已确认的问题

上一版改用 ruby-yaml 自带的 Psych.to_json，以免依赖 OpenClash 未安装的 ruby-json。但它仍可产生 JSON 不接受的 YAML 转义，例如 Emoji 输出为 `\U0001F680`，部分控制字符输出为 `\e`、`\L` 等。真实订阅常用 Emoji 策略组名，英文测试名称没有覆盖到这个问题。

本地使用 `🚀 节点选择 🇭🇰` 复现了解析失败。先开启广告后端、再启动代理时，后台接入也会遇到同一错误，前一次成功回执不能证明后续代理同步成功。

## 修改

- 新增 `yaml-json.rb`：只使用已有 ruby-yaml 安全读取配置，从解析后的原始数据生成标准 JSON。原样保留中文、Emoji、反斜杠字面值与控制字符，不使用全局替换修补转义。
- 保持安全读取，限制嵌套深度；拒绝循环、对象标签、非字符串键与 NaN/Infinity，不输出配置内容。
- `adapter.uc` 调用此转换器；转换失败提供单独的固定错误原因。
- 更新 IPK/APK 文件清单，确保新的转换器随安装包交付；没有新增路由器依赖。

## 验证范围

新增测试覆盖 Emoji/中文策略组、全部 ASCII 控制字符、YAML 专用转义、字面量反斜杠、别名、异常类型与两种启动顺序。启动顺序测试使用真实 ucode/UCI 和配置转换器，代理重启与分类库为受控环境。

隔离 OpenWrt rootfs 使用真实 Ruby 包、rc.common、原生 OpenClash 钩子阶段和 Mihomo，配置使用 Emoji 策略组名；同时检查 Redir-Host/Fake-IP、UDP/TCP、A/AAAA、规则更新及关闭恢复。分流检查使用真实 Mihomo 与本地 DNS/SOCKS/HTTP 目标，检查国内直连、国外 DNS 经代理及连接路径。

本轮未连接用户路由器。Google 与 ChatGPT 的实际访问差异尚缺终端 DNS/连接结果，不能仅凭页面红点或一个网站能打开确定原因；此修复不等同于真实节点与公网访问已经通过。完整证据见 [v0.14.2](evidence/v0.14.2/)。
