# Windows 环境配置

本文说明如何在 Windows 工作站上复现本项目的 Python 开发环境。项目主目录为：

```text
D:\Projects\nokov_hand
```

## 1. Python 环境

当前已验证环境：

```text
Python: 3.11.9
虚拟环境: D:\venvs\nokov_hand
项目目录: D:\Projects\nokov_hand
```

如果需要重新创建虚拟环境：

```powershell
D:\py311\python.exe -m venv D:\venvs\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m pip install --upgrade pip setuptools
```

安装依赖：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m pip install -r requirements.txt
```

如果要严格复现当前机器上的已验证依赖版本：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m pip install -r requirements-lock.txt
```

## 2. NOKOV/XINGYING SDK

项目依赖厂商提供的 Python SDK。GitHub 仓库不包含厂商 wheel、DLL、安装包或 License。

当前本机资料路径：

```text
D:\GPTwork\hand_mocap\XING_Python_SDK-4.1.0.5645
```

建议将 SDK wheel 从 NAS 或厂商资料复制到：

```text
D:\Projects\nokov_hand\vendor\nokovpy-3.0.1-py3-none-any.whl
```

然后安装：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m pip install .\vendor\nokovpy-3.0.1-py3-none-any.whl
```

验证：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -c "from nokov.nokovsdk import PySDKClient; c=PySDKClient(); print('.'.join(str(x) for x in c.PyNokovVersion()))"
```

预期可看到类似：

```text
4.0.56.34
```

## 3. REVO2 SDK

REVO2 控制依赖强脑科技官方 SDK 包：

```text
bc-stark-sdk
```

安装方式：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m pip install "bc-stark-sdk>=2.0,<3"
```

如果实验室使用离线安装包，请从 NAS 中复制对应 wheel 后安装。

## 4. PyCharm 配置

推荐用 PyCharm 打开：

```text
D:\Projects\nokov_hand
```

解释器选择：

```text
D:\venvs\nokov_hand\Scripts\python.exe
```

如果 PyCharm 终端没有显示虚拟环境前缀，可在 PyCharm 中检查：

```text
Settings -> Project -> Python Interpreter
Settings -> Tools -> Terminal -> Activate virtualenv
```

## 5. Git

本项目使用本地 Git 管理版本。

常用检查命令：

```powershell
git status
git log --oneline -5
```

GitHub 远程仓库：

```text
https://github.com/YUUKINANA/NOKOV-data-pipeline
```

上传前务必确认 `.gitignore` 生效，避免上传数据、视频、License 和厂商 SDK。

## 6. ROS 2 可选环境

ROS 2 不是当前主线必需步骤。此前已在 Pixi 环境中跑通过 ROS 2 Jazzy 桥接：

```text
D:\ros2_jazzy
```

如需使用：

```powershell
Set-Location D:\ros2_jazzy
pixi run bridge
```

桥接脚本位于：

```text
D:\Projects\nokov_hand\mocap\nokov_ros2_bridge.py
```

