# AdZero 在线使用文档

线上地址：<https://slobys.github.io/AdZero/>。沿用 [NaiLink](https://github.com/slobys/NaiLink/tree/main/docs/site) 的标准库静态文档框架（MIT），没有新增构建或浏览器依赖，不打包进路由器。

在仓库根目录执行：

```sh
python docs/site/build.py
python -m http.server 4173 --directory .build/docs-site --bind 127.0.0.1
```

浏览器打开 <http://127.0.0.1:4173>。正文和目录不依赖 JavaScript；中文搜索、主题和命令复制在本地浏览器处理，无统计脚本或第三方字体。

- `site.json`：版本、发行标签、页面及侧栏顺序。与 Makefile、安装器保持一致。
- `content/*.html`：面向用户的正文，二、三级标题需有唯一 `id`。站内链接使用 `page.html#anchor`。
- `$version`、`$release` 在构建时替换；正文中的美元符号写 `$$`。
- `template.html`、`site.css`、`site.js`：布局、中文搜索、复制、主题和手机目录。
- `assets/`：仅公开 Logo 等资源。不要放个人配置、诊断包或用户截图。

构建检查站内链接、锚点、图片、搜索落点和输出文件范围。运行 `python -m unittest discover -s tests/docs -p "test_*.py"` 验证。默认分支推送后由 `.github/workflows/docs.yml` 自动发布，PR 仅构建；只上传 `.build/docs-site`。
