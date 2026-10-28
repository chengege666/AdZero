# iStoreOS ARM64 私有离线试装预检

> **开发候选，不是正式发布/设备验收。** 不加入公开 `releases.tsv` 或 `sdk_verified`，不提供自动安装和 LuCI 在线更新入口。内部 APK 版本仍为 `0.21.5-r1`，不能覆盖已发布 v0.21.5 的不同字节。

## 已验证的原厂目标

| iStoreOS 固件 | target | ABI | feeds | 原厂预装包 | 离线验证 |
|---|---|---|---|---|---|
| 25.12.6 revision 2026102312 ARMSR | `armsr/armv8` | `aarch64_generic` | 13 | 1,018 | 原生编译、6 个缺失依赖闭环、7 包离线模拟通过 |
| 25.12.6 revision 2026102312 R6XS | `rockchip/armv8` | `aarch64_generic` | 15 | 940 | 原生编译、6 个缺失依赖闭环、7 包离线模拟通过 |

两套固件的原厂镜像及来源哈希已独立核验，详见 [ARM64 构建证据](ARM64.md)。两者 CPU ABI 一样，但原厂固件和依赖来源不同；不得跨厂商/目标拼装。

## 生成独立的只读候选包

维护者在已有原厂 Buildroot 及官方未压缩固件镜像的 Linux 机器上执行：

```sh
python3 scripts/build_istoreos_pilot.py \
  --profile armsr \
  --source .sdk/istoreos-armsr-2026102312-source \
  --image .sdk/istoreos-arm64-original-images/istoreos-25.12.6-2026102312-armsr-squashfs-combined-efi.img \
  --output dist/adzero-istoreos-armsr-pilot-20261029

python3 scripts/build_istoreos_pilot.py \
  --profile rockchip-r6xs \
  --source .sdk/istoreos-r6xs-2026102312-source \
  --image .sdk/istoreos-arm64-original-images/istoreos-25.12.6-2026102312-r6xs-squashfs.img \
  --output dist/adzero-istoreos-r6xs-pilot-20261029
```

生成器重新校验原厂源码、固件镜像 SHA、target、ABI、APK 文件、递归依赖与原始 APK 数据库的无网络模拟。输出同名目录与 ZIP。每包包含 `packages/` 下一个 AdZero APK 加六个目标原厂依赖，以及 `profile.tsv`、`pilot-manifest.json`、`SHA256SUMS`、`README.txt`、`preflight.sh`；**不包含 `install.sh` 或 `releases.tsv`**。目标已存在时拒绝覆盖。所有候选清单强制写 `publishable=false`、`installation_enabled=false`、`device_acceptance=not_run`。

SHA256SUMS 只用于检测文件完整性，**不是数字签名或发布者身份认证**。只通过可信渠道传输，不把 ZIP 上传到公开 GitHub Release 或软件源。

## 已通过的隔离系统快照验收

```sh
python3 scripts/check_istoreos_pilot_snapshot.py \
  --profile armsr \
  --source .sdk/istoreos-armsr-2026102312-source \
  --image .sdk/istoreos-arm64-original-images/istoreos-25.12.6-2026102312-armsr-squashfs-combined-efi.img \
  --pilot dist/adzero-istoreos-armsr-pilot-20261029
```

R6XS 要替换为其自身 `--profile rockchip-r6xs`、源码、镜像和测试包。该脚本用原厂官方镜像中的软件包数据库临时副本与相同厂商的真实 apk-tools，执行测试包预检与无网络依赖模拟。证据见 [ARMSR](evidence/istoreos-25.12.6/armsr-readonly-pilot-snapshot.json)、[R6XS](evidence/istoreos-25.12.6/r6xs-readonly-pilot-snapshot.json)。**两者均通过，但只是隔离模拟，不是实机安装、代理/DNS 或回滚测试。**

## 后续实体设备的只读步骤

先使用非唯一生产测试设备，备份原配置，准备本地 SSH/有线控制台及救援方式。通过可信传输将对应 ZIP 解压后完整复制到测试设备。仅执行：

```sh
sh preflight.sh --check
sh preflight.sh --solver
```

`--check` 仅验证固件 ID、完整版本、十位 revision、target、ABI、包管理器、完整版 `tcpdump` 和 7 个 APK SHA。`--solver` 在前者通过后额外执行 `apk add --simulate --no-network`，严禁删除/升级现有软件或引入未知依赖。**不存在 `--install` 或 `--upgrade` 功能**，也不会修改 DNS、代理、系统软件、UCI 或重启。

如匹配失败、已安装 AdZero、存在原有管理状态或包被篡改，停止操作并保留日志。可提供脱敏的预检输出和 `/etc/openwrt_release`；不要上传代理订阅、令牌、私有配置或完整恢复日志。

## 正式开放前仍须完成

- ARMSR/R6XS 分别进行实机安装、卸载、配置备份、故障回滚和重启验收。
- LAN 设备 IPv4/IPv6、UDP/TCP DNS 阻断与正常放行、代理共存实测。
- NaiLink、PassWall、OpenClash、Nikki / 无代理场景分别验证，不改变用户节点和订阅。
- 审核真实设备证据，再以**新的软件版本**重新构建、校验对应依赖及发行清单，才可开放一键安装与在线更新。

本阶段不修改或重传已发布 v0.21.5。
