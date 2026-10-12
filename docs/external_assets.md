# 外部资料与 NAS 获取清单

GitHub 仓库只保存代码、文档、小型配置和测试代码。为了避免版权、体积、许可证和隐私问题，以下内容不随仓库上传，需要从实验室 NAS 或厂商资料中另行获取。

统一获取位置：

```text
/0-全体共享文件夹/2-仪器设备/度量光学三维动作捕捉系统
```

如果 NAS 上的实际目录名与本文略有不同，以 NAS 当前文件夹为准。建议下载到本机后仍保持“软件、License、SDK、文档、实验数据”分开的结构，避免把厂商二进制文件误放进 GitHub 仓库。

## 1. 需要额外获取的资料

| 类别 | 用途 | 建议从 NAS 获取的内容 | 是否上传 GitHub |
| --- | --- | --- | --- |
| XINGYING 软件安装包 | 启动动捕系统、加载标定工程、开启 SDK 输出 | `XINGYING软件/` 或同名安装包目录 | 否 |
| License / 加密狗资料 | 启动 XINGYING 许可证校验 | `License/` | 否 |
| NOKOV/XINGYING Python SDK | Python 采集、实时控制、ROS 2 桥接 | `SDK/Python/`、`SDK/Windows/` 或 `XINGYING SDK` 相关目录 | 否 |
| SDK 接口文档 | 查字段、回调、坐标、骨骼/刚体结构 | `XINGYING SDK接口文档.pdf/.docx` 等 | 否，文档中只写获取位置 |
| 操作手册与培训视频 | 标定、T标定、场景模板、软件操作 | `操作手册/`、`培训视频/` | 否 |
| REVO2 / 强脑科技 SDK | 控制灵巧手、安装 `bc-stark-sdk` 或离线 wheel | 若 NAS 中已有，放在 `REVO2_SDK/`；若没有，需要从强脑官方资料补充 | 否 |
| 原始实验数据 | 后续训练、调试、复现实验结果 | `实验数据/raw/` | 否 |
| 处理后数据与模型 | 后续训练结果、模型权重、评估结果 | `实验数据/processed/`、`models/` | 否 |
| 演示视频/截图 | 汇报、答辩、过程记录 | `演示视频/`、`截图/` | 否 |

## 2. 本机推荐放置方式

为减少文档路径替换成本，推荐新机器按以下方式放置：

```text
D:\Projects\nokov_hand\                 # GitHub源码仓库
D:\venvs\nokov_hand\                    # Python 3.11虚拟环境
D:\Projects\nokov_hand\vendor\          # 临时放SDK wheel；已被.gitignore排除
D:\ros2_jazzy\                          # 可选：ROS 2 Pixi环境
```

其中 `vendor/` 只用于本机安装，不应提交到 GitHub。安装完成后，即使删除 `vendor/` 中的 wheel，虚拟环境通常仍可使用；但为了可复现，建议在 NAS 中保留原始 SDK 文件。

## 3. 当前项目已验证过的关键外部项

- XINGYING/NOKOV SDK 版本：`4.0.56.34`。
- XINGYING SDK 服务地址：`10.1.1.198`。
- REVO2 串口参数：`COM3`、`460800`、`slave_id=127`。
- 普通项目环境：Python `3.11.9`。
- ROS 2 可选环境：Pixi + ROS 2 Jazzy，独立于普通 Python 环境。

这些值是当前工作站的实测值，不一定是每台电脑的固定值。换机器后至少需要重新确认：

1. XINGYING 是否能正常启动并识别相机；
2. XINGYING 的 SDK/NIC 地址是否仍为 `10.1.1.198`；
3. REVO2 在设备管理器中的串口号是否仍为 `COM3`；
4. 本机安装的 SDK 版本是否与项目代码兼容。

## 4. GitHub 与 NAS 的分工

建议按下面原则维护：

- GitHub：代码、中文说明、可复现实验流程、依赖列表、测试代码。
- NAS：厂商安装包、SDK、License、培训视频、原始数据、处理数据、模型、演示视频、完整备份。

也就是说，导师或同学从 GitHub 克隆项目后，还需要按本文件从 NAS 下载外部资料，才能完整复现实机采集和灵巧手控制链路。
