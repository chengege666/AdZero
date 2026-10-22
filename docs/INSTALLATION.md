# 安装与恢复

本页适用于 v0.14.1 测试版。先查看 [兼容矩阵](COMPATIBILITY.md)，使用与固件完整版本、设备目标和包管理器对应的安装包。

## 在线安装

以 root 登录路由器 SSH，确保有 `curl`，执行：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.14.1/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh
```

安装器核对固件版本、设备目标、包架构与 SHA-256，备份配置、安装依赖，然后尝试启用保护。未匹配的固件或架构会停止安装，不要绕过检查跨版本装包。依赖从固件原有的软件源安装，不升级整套固件。

安装后打开「服务 → AdZero」。若想先安装、以后手动开启，在安装器命令后加 `--no-enable`：

```sh
sh /tmp/adzero-install.sh --no-enable
```

## 升级

已有 AdZero 时使用：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://raw.githubusercontent.com/slobys/AdZero/v0.14.1/scripts/install.sh -o /tmp/adzero-install.sh && sh /tmp/adzero-install.sh --upgrade
```

升级器先校验安装包，暂停后台调度并等待当前任务完成，再备份配置和恢复记录，调用旧版关闭与恢复，最后安装并重新开启。个人规则选择、放行名单和 DNS 选择会保留。

等待旧任务默认最多 180 秒，每 15 秒反馈。安装器不会为升级终止当前任务或删除操作锁；等待超时或恢复失败会停止升级并保留记录。普通退出或 `Ctrl+C` 会尝试恢复本次暂停的调度器。

升级完成后刷新 LuCI；资源仍旧时按 `Ctrl + F5`。

## 下载发行包安装

从 [v0.14.1 发行页](https://github.com/slobys/AdZero/releases/tag/v0.14.1) 下载发行归档，在路由器上解压并进入包含 `install.sh` 的目录：

```sh
sh install.sh --local-dir "$(pwd)"
```

已有版本加 `--upgrade`。发行归档未捆绑全部依赖，安装依赖仍可能需要联网。

当前 APK 是开发者未签名测试包。安装器只对已通过 SHA-256 核对的本地 APK 使用 `--allow-untrusted`；文件校验用于检测损坏，下载来源的可信度依赖 GitHub HTTPS。

## 常见情况

### v0.12.0 提示“没有唯一匹配此固件版本的 SDK 安装包”

v0.12.0 的发布清单由 Windows 生成，CRLF 行尾使旧安装器无法匹配最后一列包格式，三个已支持组合均可能受影响。请使用上面的 **v0.14.1 升级命令**；本版清单固定为 LF，安装器也兼容 CRLF，固件、target、架构、唯一条目和 SHA-256 检查仍保留。

该错误发生在升级暂停调度、关闭旧版和安装软件包之前，这一次匹配失败没有改动已有配置，无需先卸载。

### 等待操作锁超时

可能有任务仍在运行，也可能保留了异常中断的锁。先读取：

```sh
ls -la /tmp/adzero.lock
cat /tmp/adzero.lock/owner 2>/dev/null
ps w | grep -E '[a]dzero/(ctl|watch|adapter|backend|policy|sources|job)'
```

保留输出供排查，不直接删除锁或恢复记录。安装器不能加速已经运行的旧版任务。

### NaiLink 授权或重载未确认

先只读检查：

```sh
/usr/libexec/adzero/adapter nailink-status
/usr/libexec/adzero/ctl status
```

授权被拒绝、重载超时与配置未恢复是不同情况，处理方法见 [NaiLink 重载确认与恢复](NAILINK_RELOAD_CONFIRMATION.md)。不要通过删除 `adapter.json` 跳过恢复。

### 提示缺少推荐工具

adblock-fast 可能提示缺少 `gawk`、GNU `grep` / `sed`、`coreutils-sort`。这是后端推荐项；不能单凭这条提示判断安装或过滤失败，应结合具体错误和运行状态检查。

## 卸载

使用 APK：

```sh
/usr/libexec/adzero/ctl disable && apk del luci-app-adzero
```

使用 OPKG：

```sh
/usr/libexec/adzero/ctl disable && opkg remove luci-app-adzero
```

先恢复 AdZero 管理的设置，成功后才执行卸载。关闭或卸载不会把个人订阅选择重置成安装默认值。恢复失败时保留记录，先检查错误，不强制卸载。

## 备份与隐私

安装器备份位于 `/etc/adzero-backups/`。`/etc/adzero/adapter.json` 和升级备份中的 `state.tar.gz` 可能包含原有 DNS 或代理配置，保留在路由器本地，不要公开上传。提交问题时提供必要状态和固定前缀错误，隐藏密钥、令牌与订阅地址。
