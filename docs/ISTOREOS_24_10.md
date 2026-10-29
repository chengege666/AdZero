# iStoreOS 24.10.8 兼容适配（原厂 OPKG / IPK）

目前处于**候选构建与验收阶段，尚未向公众开放安装**。此页面记录可重复验证的适配边界，不表示 iStoreOS **全部 24.10.x** 都已经支持。

## 第一批精确固件目标

| 原厂固件 | 架构 | 固件 target | 软件包格式 |
| --- | --- | --- | --- |
| iStoreOS **24.10.8 / 2026073111** | x86_64 | \`x86/64\` | OPKG / IPK |
| iStoreOS **24.10.8 / 2026073111** | ARM64 ARMSR | \`armsr/armv8\` | OPKG / IPK |
| iStoreOS **24.10.8 / 2026073111** | ARM64 R6XS | \`rockchip/armv8\` | OPKG / IPK |

来自官方固件下载站 \`https://fw.koolcenter.com/iStoreOS/\` 的 3 个原厂镜像已经通过其原始 SHA-256、解压后的 RAW SHA-256、SquashFS 固件信息和已安装软件数据库检查。三套镜像分别预装 1041、1001、922 个 OPKG 软件包，均保留完整版 \`tcpdump\`。

## 依赖核验

原始系统尚未安装 AdZero 所需的以下 7 个包：\`adblock-fast\`、\`conntrack\`、\`coreutils-timeout\`、\`libnetfilter-cthelper0\`、\`libnetfilter-cttimeout1\`、\`libnetfilter-queue1\`、\`ucode-mod-socket\`。

这些依赖均已从三组固件各自已有的、固定版本号 24.10.8 的 Cernet 原厂镜像软件源下载；21 份 IPK 的文件 SHA-256 均与原厂 \`Packages.gz\` 索引一致。其他预装软件不需要更新或卸载。

已在**隔离系统快照**中使用原厂 iStoreOS 24.10.8 提取的 OPKG 程序、原始已安装数据库和全部安装文件清单，运行 8 包 \`--noaction\` 事务模拟：三种目标均能解算出相同的 8 个包，没有删除、升级或已安装文件冲突警告。**目前模拟使用格式正确的 AdZero 开发预览 IPK；这不等于真实原厂 Buildroot 编译成功，也不等于路由器实际安装通过。**

每个固件配置、镜像、软件源、IPK 和依赖的校验记录见 [原厂候选证据](evidence/istoreos-24.10.8/original-image-opkg-dependency-readiness.json)。

## 为什么不能直接使用 iStoreOS 25.12 的安装包？

iStoreOS 24.10.8 使用的是 **OPKG / IPK**，不是 25.12.6 的 **APK**。直接混装可能导致依赖失效、软件包冲突或网络服务异常。24.10.8 的三组原厂 feeds 各自固定，R6XS 还带有独立的板型标识。

专用试装源码 \`scripts/install_istoreos_24108_beta.sh\` 只接受精确固件修订号、target 和 CPU 架构；会验证安装包 SHA-256、执行离线 OPKG 预检，备份配置，默认不启用广告过滤，并在卸载前优先恢复 AdZero 管理的 DNS/代理设置。**它还不是公开发布的安装入口。**

## 还需要验证什么？

- 用对应 iStoreOS 24.10 厂商 Buildroot **真正构建三份原生 LuCI IPK**，确认正确 OPKG 封装、源码、厂商 feeds、target 和 SHA-256。
- 用原生编译后的 IPK **重新执行**原厂 OPKG 快照的完整依赖与文件冲突检查。
- 完成独立测试版的中文菜单/一键分流测试，才将通过验收的精确目标接入 \`scripts/install-auto.sh\` 并上传新的 GitHub **Pre-release**。
- 实体设备 LAN DNS、代理共存、重启、关闭和恢复需用户自愿测试；未经真实设备测试不会宣称稳定支持。

原厂 24.10 发布页没有提供可证明此次镜像所用 **精确 Git 源码提交**的历史 \`commit.buildinfo\`。构建候选只能使用当时的历史源码快照并明确标注：**该快照未获原厂精确构建提交证明**，不能把历史近似版本冒充已经认证的原厂 SDK。

如果您想先检查自己使用的版本，可在软路由 SSH 执行 \`cat /etc/openwrt_release\`。旧的 \`24.10.7\`、其他 \`24.10.x\` 或不同修订号目前**均不开放强制安装**。
