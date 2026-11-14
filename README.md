# Visual Pandas Studio · 可视化数据分析工作台

[![CI](https://github.com/250521Y/visual-pandas-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/250521Y/visual-pandas-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

在浏览器中完成数据导入、清洗、转换、统计分析、图表联动和报告导出。使用 React + TypeScript 构建界面，FastAPI + Pandas 执行真实计算，SQLite 保存操作快照。

A browser-based data analysis workbench powered by React, FastAPI and Pandas. Import spreadsheets, clean and transform data, explore statistics, create linked charts, and export reports. The interface supports Chinese and English.

## 功能

- 导入 CSV、XLSX、XLS，预览数据、字段类型和缺失值。
- 数据清洗、筛选、排序、分组聚合、透视、合并及时间序列处理。
- 描述统计、相关性分析和统计检验。
- 多种 ECharts 图表、数据选择联动和可视化配置。
- 操作预览、版本校验、历史快照、撤销与重做。
- 导出 CSV、Excel、项目 JSON，以及可通过浏览器打印为 PDF 的分析报告。
- 中英双语、浅青色与藕粉色主题；内置 Iris、Titanic、Sales 示例。

## 本地运行

需要 Python 3.10–3.12、Node.js 22 或 24，以及 Git。推荐 Python 3.11 + Node.js 22。

```bash
git clone https://github.com/250521Y/visual-pandas-studio.git
cd visual-pandas-studio
```

打开两个终端，分别启动后端和前端。

Windows PowerShell 后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

macOS / Linux 后端：

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另一终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

Windows 如果执行策略阻止 `npm`，使用 `npm.cmd`。打开 <http://127.0.0.1:5173/>；后端健康检查为 <http://127.0.0.1:8000/api/health>，接口文档为 <http://127.0.0.1:8000/docs>。开发服务器会把 `/api/` 请求转发到本机后端。

## 环境配置

默认配置可以直接本地运行。需要自定义时，将根目录 `.env.example` 复制为 `.env`，在 `backend/` 目录启动后端时添加 `--env-file ../.env`。数据默认保存在 `backend/runtime/`，也可通过 `VPS_DATA_DIR` 指定；相对路径以启动进程的工作目录为基准。

前端配置见 `frontend/.env.example`，自定义值写入 `frontend/.env.local`。生产环境由 Nginx 同域代理 `/api/` 时，保持 `VITE_API_BASE` 为空。

上传大小、行列数、会话数据集数量、历史数量和保留天数等限制见 `.env.example`。运行数据库、环境文件和用户上传内容不应提交到 Git。

## 测试与构建

后端在 `backend/` 目录执行：

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest tests -q
```

```bash
# macOS / Linux
.venv/bin/python -m pytest tests -q
```

前端在 `frontend/` 目录执行：

```bash
npm test
npm run build
```

构建产物为 `frontend/dist/`。GitHub Actions 会在推送和 Pull Request 时运行后端测试、前端测试和生产构建。

可选报告 PDF 验证需要另外安装 Playwright（在 `frontend/` 执行 `npm install --no-save --package-lock=false playwright`），启动前后端后执行 `node tools/verify-report-pdf.cjs`。默认使用已安装的 Chrome，也可用 `VPS_BROWSER_CHANNEL=msedge` 选择 Edge；结果写入被 Git 忽略的 `output/pdf/`。此工具会创建并在完成后删除它自己的测试数据集。

## 项目结构

```text
backend/
  app/                 FastAPI 接口、Pandas 运算、数据和快照管理
  data/                内置 CSV 与来源说明
  tests/               后端功能和接口测试
  tools/               可选压力测试工具
  prepare_data.py      可选示例数据生成脚本
  requirements.txt
frontend/
  src/                 页面、组件、状态、双语词条与前端测试
  public/              网站图标
  tools/               可选报告 PDF 验证工具
  package.json
  package-lock.json
deploy/                Ubuntu + Nginx 部署与验收脚本
.github/               自动测试和协作模板
```

页面路由：`/`、`/datasets`、`/cleaning`、`/transform`、`/statistics`、`/visualization`、`/reports`。各页面共享当前数据集；切换语言保留分析状态。

## 部署

先运行前端构建，再将项目放到 Ubuntu 服务器的 `/var/www/visual-pandas-studio`。部署脚本会安装 Python 和 Nginx 等系统依赖，并配置 systemd 服务及 HTTPS；请先阅读脚本，准备域名解析后执行：

```bash
sudo bash deploy/install.sh --domain analysis.example.com --email you@example.com
```

将示例域名和邮箱替换为自己的值。`--http-only` 可跳过证书申请。脚本保留已有环境配置，并备份它将更新的配置文件。后端监听本机 `8000`，Nginx 提供网页和 `/api/`；运行数据保存在 `/var/lib/visual-pandas-studio`。

当前应用通过浏览器会话标识隔离数据，未提供账号登录与角色权限。处理私有数据时，应在反向代理或部署环境增加访问控制；具体边界见 [SECURITY.md](SECURITY.md)。这是包含 Python 后端的完整应用，GitHub Pages 不能独立运行它。

## 示例数据与许可

原创项目代码使用 [MIT License](LICENSE)。第三方依赖和数据保留各自的许可与来源；数据集说明见 [backend/data/README.md](backend/data/README.md)。应用启动不需要下载数据。重新生成示例数据时，额外安装 `scikit-learn`，然后在 `backend/` 执行 `python prepare_data.py`；仅当 Titanic CSV 不存在时脚本才会下载该数据。

欢迎通过 [Issues](https://github.com/250521Y/visual-pandas-studio/issues) 反馈问题，或提交 Pull Request。开发与贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)。
