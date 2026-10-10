# GitHub 与 NAS 发布清单

本文用于在上传 GitHub 和同步 NAS 前做检查。

## 1. GitHub 仓库

当前仓库：

```text
https://github.com/YUUKINANA/NOKOV-data-pipeline
```

建议保持私有仓库。

GitHub 保存：

- 源代码；
- 中文 README；
- 开发文档；
- 小型配置；
- 测试代码；
- 依赖说明。

GitHub 不保存：

- 原始实验数据；
- 处理后的大数据；
- 模型文件；
- 厂商 SDK；
- XINGYING 软件安装包；
- License；
- 加密狗相关文件；
- 演示视频；
- 私人路径、账号、密钥。

## 2. 上传前检查

检查 Git 状态：

```powershell
Set-Location D:\Projects\nokov_hand
git status
```

确认不会上传以下内容：

```text
data/raw/
data/processed/
models/
vendor/
License/
SDK/
*.mp4
*.zip
*.7z
*.whl
*.dll
*.pyd
*.lic
.env
```

可用命令检查即将提交的文件：

```powershell
git status --short
git diff --stat
git ls-files
```

## 3. 推荐 NAS 结构

```text
动捕数据采集链路/
├─ 代码仓库备份/
│  ├─ NOKOV-data-pipeline_YYYYMMDD.zip
│  └─ git_bundle/
├─ 厂商资料/
│  ├─ XINGYING软件/
│  ├─ XINGYING_SDK/
│  ├─ License/
│  └─ REVO2_SDK/
├─ 实验数据/
│  ├─ raw/
│  └─ processed/
├─ 演示视频/
└─ 文档导出/
```

## 4. GitHub 首次上传流程

配置 remote：

```powershell
git remote add origin https://github.com/YUUKINANA/NOKOV-data-pipeline.git
```

如果 remote 已存在：

```powershell
git remote set-url origin https://github.com/YUUKINANA/NOKOV-data-pipeline.git
```

提交：

```powershell
git add README.md docs data/README.md ml mocap revo2 tests requirements.txt requirements-lock.txt .gitignore
git commit -m "Prepare project documentation for GitHub"
```

推送：

```powershell
git push -u origin main
```

## 5. 上传后检查

在 GitHub 网页上检查：

- README 是否正常显示中文；
- 文档链接是否有效；
- 是否误传了数据、视频或厂商文件；
- 仓库是否仍为 Private；
- 最近提交记录是否清楚。

## 6. NAS 同步建议

GitHub 上传后，NAS 保存两类内容：

1. 代码备份：可直接复制整个 Git 仓库，或导出 zip。
2. 附件资料：厂商软件、SDK、License、实验数据、视频。

建议每次重大实验后同步：

- 当天代码提交号；
- 对应实验数据；
- 实验备注；
- 演示视频或截图。

