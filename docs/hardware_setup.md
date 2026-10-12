# 硬件与 XINGYING 启动流程

本文记录动捕系统和 REVO2 灵巧手的启动顺序。建议每次实验都按相同顺序操作，减少网络、串口和 SDK 连接问题。

## 1. 设备组成

当前使用：

- XINGYING/NOKOV 光学动作捕捉系统；
- 12台动捕相机；
- 交换机；
- Windows 工作站；
- 强脑科技 REVO2 灵巧手；
- USB-RS485 转接器；
- XINGYING 软件与 License/加密狗。

XINGYING 软件、License、SDK、操作手册和培训视频不随 GitHub 仓库上传，统一从 NAS 获取：

```text
/0-全体共享文件夹/2-仪器设备/度量光学三维动作捕捉系统
```

具体清单见 [`external_assets.md`](external_assets.md)。

## 2. 动捕系统启动

1. 连接相机阵列与交换机。
2. 连接工作站与交换机。
3. 给交换机和相机阵列供电。
4. 如 XINGYING 软件提示，插入加密狗或选择 License 文件。
5. 打开 XINGYING 软件。
6. 加载已标定工程。
7. 确认相机列表显示 `12/12` 在线。
8. 在 3D 视图中确认相机空间位置正确。
9. 移动反光点，确认 XINGYING 能实时识别。
10. 确认 SDK 数据输出已开启。

默认 SDK 服务地址：

```text
10.1.1.198
```

如果连接失败，优先检查：

- 有线网卡 IPv4 设置；
- XINGYING 是否处于 Live Mode；
- SDK/NIC 设置是否选择了正确网卡；
- 防火墙是否阻挡；
- 相机和交换机供电是否正常。

## 3. 手部贴点

当前 24点手部模型使用 XINGYING 手部模板对应编号。语义说明保存在代码和处理结果中：

```text
ml/synthetic_hand_pipeline.py
data/processed/.../marker_layout.csv
```

左/右手可能使用不同 SDK marker ID 范围。处理代码会自动将常见的 `25..48` 右手编号映射回语义编号 `1..24`。

## 4. REVO2 灵巧手连接

已验证参数：

```text
PORT: COM3
BAUDRATE: 460800
DEVICE_ID / slave_id: 127
```

使用 Python 控制前：

1. 确认 REVO2 电量充足。
2. 连接 USB-RS485 转接器。
3. 确认设备管理器中端口号，例如 `COM3`。
4. 完全退出强脑官方桌面软件，避免串口被占用。
5. 确认灵巧手周围没有硬物、线缆或人体遮挡。

状态检查：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions status
```

单次发送测试：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions send 400 399 120 50 50 49 --speed 100
```

张开：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions open --speed 100
```

## 5. 安全停止

动捕采集脚本停止：

```text
Ctrl+C
```

等待终端出现保存完成信息后再关闭窗口。

REVO2 实时控制脚本停止：

```text
Ctrl+C
```

如需手动张开：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions open --speed 100
```

