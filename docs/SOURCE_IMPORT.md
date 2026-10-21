# WebCodex 源码导入记录

2026-10-21 将 `/home/naiyou/webcodex/projects/workspace/adzero` 中的 v0.3.1
源码、文档、测试和两个历史 IPK 导入当前本地仓库。

- 共 18 个原始文件，下载后逐个比较字节数和 SHA-256，全部一致。
- 排除 Python 缓存，不携带远端父目录 Git 仓库、其他项目或配置凭据。
- 原始归档：`artifacts/source-import/adzero-webcodex-v0.3.1.tar.gz`。
- 归档 SHA-256：`9335979b2e138a247285bed4f35dc5d3d746df4c48509ddd11c5337c4c3deb1a`。
- 逐文件哈希与远端权限：`artifacts/source-import/manifest.json`。
- 原有 50 项 Python 测试、LuCI 模拟与语法检查已在本地 Ubuntu/WSL 复现通过。
- 导入后新增 `.gitattributes` 固定文本为 LF；安装包生成器与 SDK 入口显式设置可执行权限。

后续 v0.4.0 开发在本地进行；远端源码保留原样。历史 IPK 不会被新版本覆盖。
