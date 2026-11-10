# 手册维护与导出

正文只编辑上级目录的 [Markdown](../AI-Agent课程知识手册.md)。清单元数据在 [catalog.py](catalog.py)；图源在 [assets](../assets)。构建不导入或修改课程业务代码，不安装依赖，不读取模型密钥。

## 已验证的工具来源

本机 Codex bundled runtime 提供 marked、Sharp、ReportLab、pypdf、pdfplumber、Pillow 和 Poppler。PDF使用 Windows SimHei 中文字体及 Consolas 等宽字体，正文与代码保持可搜索文本。SVG 原件为可编辑文本，PNG 只在忽略的 .build 中作为 PDF 中间图。

默认脚本按当前用户缓存定位 bundled runtime。其他机器先提供等价工具路径：

- HANDBOOK_NODE_MODULES：含 marked/Sharp 的已有 node_modules 根目录。
- HANDBOOK_PYTHON：已有 ReportLab/pypdf/pdfplumber 的 Python 可执行文件。
- HANDBOOK_CJK_FONT：可嵌入的 TrueType 中文字体文件。
- HANDBOOK_MONO_FONT：等宽 TrueType 字体；缺省尝试 Windows Consolas。

这些环境变量只是文档工具配置，不使用 AI_AGENT_* 或课程 .env。脚本没有安装操作；缺工具时应按可信文档环境准备，不改变项目依赖。

## 维护顺序

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -B docs/course-handbook/tools/prepare.py
node docs/course-handbook/tools/build.mjs
```

prepare.py 重建清单、来源摘要、目录/源码索引和六张SVG。修改 SVG 后只需运行 build.mjs 导出；再次 prepare 会按图示定义重建SVG。修改图布局可编辑 prepare.py 的 figures()，不要误把 PNG 当源文件。

正文目录使用稳定显式锚点；新增知识点时保留已发布编号，更新 catalog、正文、自测答案和覆盖表。当前清单是108项基线，扩展时同时调整检查脚本的预期数量。

## 检查

用 bundled Python（不是缺少PDF库的课程 .venv）执行：

```powershell
& "$env:USERPROFILE/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe" -X utf8 -B docs/course-handbook/tools/check.py --examples --pdf
```

链接检查覆盖主文档、清单、质量报告和本说明；核对27章、108知识点/题目/答案、30大纲项、历史V编号、来源摘要和SVG。五个可运行Python短例在课程既有.venv中执行，不发网络请求。

PDF检查包含书签、链接、知识/题目编号、字体嵌入和字符安全边界；不能替代实际渲染。使用已安装 pdftoppm 把PDF全页转成PNG，在 .build 内制作联系表逐页看布局，并放大长表、代码和中文页。最终证据只写手册自己的质量报告，不回填原课程工程状态。

PDF的源码文件链接使用相对路径，需与仓库保持目录关系；单独打印或拷走PDF时，可按附录F的文件名/符号回仓库检索。主Markdown更适合复制代码。

## 生成物

- PDF为可交付文件；主Markdown为唯一正文来源。
- .build 保存解析tokens、图示PNG、检查JSON、全页渲染和联系表，受本目录.gitignore忽略。
- source-snapshot.json保留已盘点课程文件的SHA-256、行数和Python AST符号，不包含运行环境变量或密钥。
- 若课程源文件有变化，先检查差异再有意重建快照；不要仅为消除drift警告就直接覆盖基线。
