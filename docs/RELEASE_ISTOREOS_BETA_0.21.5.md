# AdZero iStoreOS 25.12.6 公开一键安装测试版

版本标签：**v0.21.5-istoreos-beta.1**。这是独立的 GitHub **Pre-release**，不是正式稳定认证版。APK 内部版本仍为 `0.21.5-r1`，来源于分别验证过的原厂 Buildroot；该测试渠道**不覆盖**已发布的 v0.21.5 APK，也不修改普通 OpenWrt / ImmortalWrt 一键安装目录或 LuCI 稳定更新规则。

## 适用设备（必须精确匹配）

| 系统 | target | 包架构 | 原厂专用包 |
| --- | --- | --- | --- |
| iStoreOS 25.12.6 / revision 2026102312 | `x86/64` | `x86_64` | 专用 x86 APK + 原厂 6 个依赖 |
| iStoreOS 25.12.6 / revision 2026102312 | `armsr/armv8` | `aarch64_generic` | ARMSR APK + 原厂 6 个依赖 |
| iStoreOS 25.12.6 / revision 2026102312 | `rockchip/armv8` | `aarch64_generic` | R6XS APK + 原厂 6 个依赖 |

R6XS 还检查官方镜像支持的五种精确板型标识；同样的 ARM64 CPU **不代表**所有 Rockchip 固件都能安装。不同版本、其他修订号、ImmortalWrt、OpenWrt 设备和不匹配的目标均会直接拒绝安装。

## 一条命令进入中文菜单

**建议在有本地管理或救援通道的测试路由器上执行。** 通过 root SSH 输入下面一条命令，下载的是当前测试发行版的专用安装器：

```sh
curl -fL --proto '=https' --proto-redir '=https' https://github.com/slobys/AdZero/releases/download/v0.21.5-istoreos-beta.1/install-istoreos-beta.sh -o /tmp/install-istoreos-beta.sh && sh /tmp/install-istoreos-beta.sh --menu
```

中文菜单提供：
1. 只读检测固件、修订号、设备 target、架构、SHA-256、依赖；
2. 一键安装（**默认不启用过滤**，推荐第一轮选择）；
3. 一键安装并启用过滤（需额外确认风险）；
4. 安全卸载（先通过控制器关闭并恢复其管理的配置，保留原厂依赖及备份）；
0. 退出。

用户**不需要输入 CPU 架构、软件包文件名或安装版本**。安装器从严格匹配的三个独立原厂压缩包自动选一个，只接受 GitHub Release 资产中事先固定于脚本的 SHA-256，并逐个校验 7 个 APK。下载走 HTTPS，不允许跳过证书验证。依赖使用 `apk add --simulate --no-network` 在安装前核验，发现会覆盖、卸载、升级原有软件包时拒绝。**真正安装也只通过本地原厂 APK 文件进行，无需在线刷新未知第三方包仓库。**

测试版安装前在本地保留权限受限的 `/etc/config` 备份，安全卸载之前要求控制器成功恢复 AdZero 管理的设置，避免遗留 DNS/代理劫持。**不能保证对第三方代理或非标准网络拓扑完全无影响**；如果没有保底连接和本地救援方式，不要在唯一生产软路由上尝试首次启用。

## 离线安装与高级选项

如果路由器无法访问 GitHub Release，可以通过可信电脑下载本次发行版的安装器及目标三种固件专用 TAR.GZ（建议都下载），复制至路由器同一目录，再运行：

```sh
sh install-istoreos-beta.sh --menu --local-dir /tmp/adzero-istoreos-beta
```

仅预检可以运行：

```sh
sh install-istoreos-beta.sh --check
```

脚本仅允许显式启用操作，非交互安装时若要求开启过滤，必须同时传入 `--enable --accept-network-risk`。已经安装 AdZero 的系统默认不被覆盖：先备份并使用原版本安全卸载，再安装本测试渠道。

## 测试者如何反馈

安装后先确认 SSH/LuCI、正常域名与互联网访问，再在 LuCI 中选择开启过滤。测试项目包括：广告域名阻断、正常网站放行、IPv4/IPv6、DNS UDP/TCP、NaiLink/PassWall/OpenClash/Nikki 共存、重启后配置保持及安全卸载恢复。

请提供**脱敏**的固件版本、target、测试版安装结果和错误信息。**不要上传**代理节点订阅、API token、私人 DNS 上游、SSH 密钥、完整 `/etc/config`、公网 IP 或个人账号。发生断网时先通过本地管理恢复，保留私有配置备份，不要强制删除保护锁。

## 构建来源与验证范围

三套安装包均从本项目此前验证过的原厂 iStoreOS 25.12.6 Buildroot 实际编译字节和六个原厂依赖中生成；原始 APK/feeds SHA、x86 KVM 安装证据、ARM64 固件原版数据库的 7 包离线模拟证据均已留档。Beta 打包程序 `scripts/build_istoreos_beta.py` 每次严格比对 source_sha256、原厂软件包 SHA、目标和 ABI，生成三个不同的 TAR.GZ 和带固定摘要的 `install-istoreos-beta.sh`。

**这个公开测试版需要用户在真实设备上补充安装、DNS、代理共存、重启和恢复验证，不能在用户反馈前声称已经通过所有机型的正式验收。** 正式验证后才能考虑将这些固件组合加入一般安装器的 `sdk_verified` 与稳定更新目录。

