# 动捕数据采集链路

本项目用于搭建一条可复现的动作捕捉数据采集与灵巧手动作复现链路。当前主线是：

```text
XINGYING/NOKOV 光学动作捕捉系统
  -> Python SDK 实时采集与保存
  -> 24点手部数据处理
  -> 6维 REVO2 灵巧手控制量
  -> 离线回放 / 实时复现 / 后续机器学习数据集
```

项目面向实验室导师和同学复现。GitHub 仓库只保存代码、文档和小型配置文件；厂商软件、SDK压缩包、License、实验原始数据、模型文件和演示视频放在 NAS 附件资料中。

## 项目阶段定位

1. **动捕驱动灵巧手实时复现**：使用 XINGYING/NOKOV 采集手部反光点，通过几何算法和安全输出层驱动 REVO2 灵巧手复现人的手部动作。
2. **家庭服务机器人示教数据采集系统**：将动捕、灵巧手、机械臂、相机等数据统一成 episode，为“叠毛巾、抓取、放置”等任务提供示教数据。
3. **面向机械臂 + 灵巧手的模仿学习前期平台**：在稳定采集链路的基础上，进一步训练“手部动捕/视觉/机器人状态 -> 控制动作”的机器学习模型。

当前已完成并验证的是第一阶段的主要链路；第二、三阶段为后续开发方向。

## 文档索引

- [Windows 环境配置](docs/setup_windows.md)
- [硬件与 XINGYING 启动流程](docs/hardware_setup.md)
- [动捕采集、处理与可视化流程](docs/mocap_pipeline.md)
- [REVO2 控制说明](docs/revo2_control.md)
- [实时复现链路](docs/live_control.md)
- [无硬件 24点合成闭环](docs/synthetic_hand_pipeline.md)
- [机器学习路线规划](docs/ml_plan.md)
- [GitHub 与 NAS 发布清单](docs/github_nas_publish.md)
- [开发进度记录](docs/progress_log.md)
- [数据字段说明](data/README.md)

截至2026-09-03，以下链路已在本机完成实际设备验证：

```text
12台相机 → XINGYING实时识别 → NOKOV SDK → Python文件采集
                                      └→ ROS 2桥接 → Topic订阅
```

已验证相机采样频率约为90 Hz，SDK版本为 `4.0.56.34`，ROS Domain ID为 `42`。

## 项目目录

- `mocap/`：NOKOV数据采集与ROS 2桥接脚本。
- `ml/`：后续的数据预处理、特征工程、训练与推理代码。
- `configs/`：项目配置文件。
- `data/raw/`：原始采集数据；每次采集自动生成时间戳文件夹。
- `data/processed/`：清洗、整理后的数据。
- `data/README.md`：四种采集文件及全部字段的详细说明。
- `models/`：训练生成的模型文件。
- `revo2/`：REVO2灵巧手通信、单次控制和素材回放脚本。
- `tests/`：自动化测试。
- `docs/`：项目说明与实验记录。
- `docs/revo2_control.md`：REVO2控制链路、命令、参数和安全注意事项。
- `docs/progress_log.md`：按日期记录已完成工作、验证结果和后续待办。

## 软件环境

- 项目目录：`D:\Projects\nokov_hand`
- 普通Python/机器学习环境：`D:\venvs\nokov_hand`
- ROS 2 Jazzy/Pixi环境：`D:\ros2_jazzy`
- XINGYING SDK原始资料：`D:\GPTwork\hand_mocap\XING_Python_SDK-4.1.0.5645`
- 默认XINGYING SDK服务地址：`10.1.1.198`

普通安装使用核心依赖文件：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m pip install -r requirements.txt
```

需要完全复现已验证环境时使用精确锁文件：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m pip install -r requirements-lock.txt
```

当前PyTorch为Intel Arc GPU对应的XPU构建。OpenCV尚未加入，因为当前数据源是SDK输出的三维坐标而不是相机图像。

## 一、启动硬件和XINGYING

每次采集或启动ROS桥接前，依次完成：

1. 连接电脑与相机交换机的网线。
2. 启动交换机及相机阵列供电。
3. 如许可证需要，插入加密狗。
4. 打开XINGYING并加载标定完成的工程。
5. 确认12台相机全部在线，界面显示 `12/12`。
6. 确认处于实时模式，并开启SDK数据输出。
7. 在3D视图中确认相机位置正常，移动反光点时能够实时识别。

只有XINGYING本身能稳定识别反光点后，才继续运行Python或ROS 2程序。

## 二、直接采集并保存数据

直接采集模式会把SDK收到的每一帧保存到磁盘，适合建立手势数据集和离线分析。当前默认使用“手部训练友好模式”：保存必要的24点、时间、骨骼段、刚体与质量信息，并在结束后自动无损压缩。

打开PowerShell，运行：

```powershell
Set-Location D:\Projects\nokov_hand

D:\venvs\nokov_hand\Scripts\python.exe .\mocap\inspect_mocap.py `
  --server 10.1.1.198 `
  --print-every 90 `
  --max-points 5 `
  --start-delay 3 `
  --duration 10
```

参数说明：

- `--server`：XINGYING SDK服务/NIC的IPv4地址。
- `--print-every 90`：每90帧打印一次终端预览；90 Hz时约每秒一次。
- `--max-points 5`：终端每类最多显示5个点，不影响文件中保存的完整数据。
- `--start-delay 3`：连接成功后等待3秒再开始录制，方便摆好手势。
- `--duration 10`：正式录制10秒后自动安全停止；填 `0` 表示一直录到手动按 `Ctrl+C`。
- `--save-mode hand`：默认值；保存手部任务必要的 `frames.csv`、已标号点 `points.csv`、`rigid_bodies.csv` 和 `skeleton_segments.csv`。
- `--save-mode full`：保存完整调试数据，包括 `raw.jsonl`、Marker Set、未识别点、刚体和 skeleton 信息。
- `--compress-on-finish`：默认开启；采集结束后把保存的文本文件无损压缩成 `.gz`，处理和回放脚本可以直接读取。
- `--no-compress-on-finish`：可选；临时保留未压缩CSV/JSON，方便用Excel或文本编辑器人工检查。
- `--output-dir PATH`：可选，自定义会话文件夹的父目录。
- `--no-save`：可选，只查看终端预览，不保存文件。

连接成功时会看到：

```text
Connecting to XINGYING SDK server: 10.1.1.198
Recording every received frame to session folder:
Connected. Waiting for frames; press Ctrl+C to stop safely.
```

采集完成后按一次 `Ctrl+C`。不要直接关闭终端，等待出现：

```text
Stopping safely; waiting for the SDK callback to finish...
Saved session folder: ...
Stopped. Unique frames received: ...; callback errors: 0
```

每次采集会生成：

批量手势采集默认就是 `--save-mode hand --compress-on-finish`，文件结构通常是：

```text
data/raw/mocap_YYYYMMDD_HHMMSS/
├─ frames.csv.gz
├─ points.csv.gz
├─ skeleton_segments.csv.gz
├─ rigid_bodies.csv.gz
└─ skeleton_descriptions.json.gz
```

调试 SDK 数据结构时可以使用 `--save-mode full`，不压缩时文件结构是：

```text
data/raw/mocap_YYYYMMDD_HHMMSS/
├─ frames.csv
├─ points.csv
├─ skeleton_segments.csv
├─ skeleton_descriptions.json
├─ raw.jsonl
└─ rigid_bodies.csv
```

采集文件的逐字段说明见 [`data/README.md`](data/README.md)。原始采集结果应保持不变，清洗、滤波、插值和特征提取结果写入 `data/processed/`。

## 三、把24点手部数据转换成6维控制量

采集完成后，每段 `data/raw/mocap_...` 数据可以离线转换成暂定的6维归一化控制量。

处理最新5段采集：

```powershell
Set-Location D:\Projects\nokov_hand

D:\venvs\nokov_hand\Scripts\python.exe -m ml.process_hand_sessions --latest 5
```

处理单独一段采集：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.process_hand_sessions `
  D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS
```

每段会生成到对应的 `data/processed/mocap_...` 文件夹：

- `controls_6d.csv`：每帧的6维输出，列名为 `command_*_0_1`，数值范围暂定为0到1。
- `controls_6d_stable.csv`：带短时丢点补偿、平滑和限速的6维输出，更接近后续实时控制要使用的形式。
- `joint_angles.csv`：中间计算出的手指角度，方便检查算法。
- `skeleton_segment_summary.csv`：如果原始数据包含 XINGYING skeleton，列出 skeleton 的 segment ID、名称和父子关系。
- `skeleton_segment_angles.csv`：如果原始数据包含 XINGYING skeleton，列出相邻骨段的相对姿态角，供后续映射到6维控制量。
- `summary.json`：帧数、有效帧、缺失点统计和每个通道的范围。
- `marker_layout.csv`：当前使用的24个点号语义。

目前这6维信号仍是几何估计结果，不是REVO2的最终电机指令。等灵巧手通信协议和实物确认后，还需要再做一次从 `0-1控制量` 到 `实际关节/电机命令` 的映射。

如果采集的是右手，XINGYING 可能把24个点的SDK ID输出为 `25..48`。处理脚本会自动识别这种情况，并在读取时映射回手部贴点表格的 `1..24` 语义编号；`summary.json` 中的 `input_marker_id_offset` 会记录本次使用的偏移量，例如右手通常为 `24`。

## 四、回放可视化24点和6维输出

可以像昨天一样看录制动作的回放：

如果想演示完整流程，直接运行 `ml/demo_hand_pipeline.py`。它会先重新计算稳定6维输出，再打开回放窗口。

如果用 PyCharm，直接运行 `ml/replay_hand_motion.py`，会弹出文件夹选择窗口。选择某个 `data/raw/mocap_...` 文件夹即可。

如果用 PowerShell，也可以显式指定一段数据：

```powershell
Set-Location D:\Projects\nokov_hand

D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion `
  --session D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS `
  --speed 0.5
```

完整演示也可以用 PowerShell：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.demo_hand_pipeline `
  --session D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS `
  --speed 0.5
```

左侧是按 XINGYING 24点表格连接的手部骨架，右侧是实时计算出的稳定6维控制条。`--speed 0.5` 表示半速回放，便于观察；去掉这个参数就是按原速度播放。

## 五、REVO2灵巧手控制

REVO2控制脚本位于 `revo2/`，详细说明见 [`docs/revo2_control.md`](docs/revo2_control.md)。

当前已验证的硬件参数：

```text
COM3 / 460800 / slave_id=127
```

单次发送6维指令：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions send 400 399 120 50 50 49 --speed 100
```

回放已处理的动捕素材，默认驱动全部6个通道：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --rate-hz 15 --speed 250 --max-position 500
```

如果要回到只驱动食指、中指、无名指、小指的四指模式：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --hold-thumb --rate-hz 15 --speed 250 --max-position 500
```

首次回放前建议先 dry-run：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --dry-run --rate-hz 15 --speed 250 --max-position 500
```

运行前应完全退出强脑官方桌面软件，避免串口被占用。

实时动捕复现，也就是“边动手、边计算、边驱动灵巧手”，使用：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.live_mocap_control `
  --server 10.1.1.198 `
  --start-delay 5 `
  --rate-hz 15 `
  --speed 250 `
  --max-position 500 `
  --max-step 35 `
  --output-deadband 10 `
  --output-quantum 5 `
  --output-alpha 0.6
```

上面这条默认只打印实时计算出的6维控制量，不打开串口。确认数据变化正常后，再正式接入灵巧手：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.live_mocap_control `
  --server 10.1.1.198 `
  --start-delay 5 `
  --rate-hz 15 `
  --speed 250 `
  --max-position 500 `
  --max-step 35 `
  --output-deadband 10 `
  --output-quantum 5 `
  --output-alpha 0.6 `
  --enable-hand
```

其中 `--output-deadband`、`--output-quantum` 和 `--output-alpha` 是最终发送前的机械安全输出层，用来减少频繁微小变化造成的抖动。如果想实时驱动的同时保存一份原始采集数据，额外加 `--record`。如果只想先驱动四指、不动拇指，额外加 `--hold-thumb`。

## 六、启动ROS 2桥接

ROS 2桥接会实时发布数据，但当前不会自动保存上述采集文件。没有明确需要时，不建议同时运行直接采集脚本和ROS桥接，以免混淆输出或增加SDK客户端数量。

保持XINGYING运行，打开第一个PowerShell终端：

```powershell
Set-Location D:\ros2_jazzy
pixi run bridge
```

`pixi run bridge` 已配置为调用：

```text
D:\Projects\nokov_hand\mocap\nokov_ros2_bridge.py
```

Pixi环境会自动设置 `ROS_DOMAIN_ID=42`。连接成功后应看到：

```text
NOKOV SDK version: 4.0.56.34
Connecting to XINGYING SDK server: 10.1.1.198
Connected; publishing live NOKOV frames as ROS 2 topics
```

随后终端约每秒打印一次帧号、点数量、刚体数量和延迟。

### 已发布话题

| 话题 | 消息类型 | 内容 |
| --- | --- | --- |
| `/nokov/frame_number` | `std_msgs/msg/UInt32` | SDK源帧号 |
| `/nokov/latency_ms` | `std_msgs/msg/Float32` | SDK报告的延迟，单位毫秒 |
| `/nokov/labeled_marker_count` | `std_msgs/msg/UInt32` | 带标签点数量 |
| `/nokov/unidentified_marker_count` | `std_msgs/msg/UInt32` | 未识别点数量 |
| `/nokov/rigid_body_count` | `std_msgs/msg/UInt32` | 刚体数量 |
| `/nokov/labeled_markers` | `visualization_msgs/msg/MarkerArray` | 带标签点，位置单位米 |
| `/nokov/unidentified_markers` | `visualization_msgs/msg/MarkerArray` | 未识别点，位置单位米 |
| `/nokov/rigid_bodies` | `visualization_msgs/msg/MarkerArray` | 刚体位置和四元数姿态，位置单位米 |

ROS中的 `frame_id` 默认为 `nokov_world`。桥接脚本会把SDK的毫米坐标转换为ROS惯用的米。

## 七、在第二个终端验证ROS数据

保持第一个桥接终端运行，再打开第二个PowerShell终端。

### 1. 查看话题

```powershell
Set-Location D:\ros2_jazzy
pixi run ros2 topic list
```

应能看到所有 `/nokov/...` 话题。

### 2. 检查接收频率

```powershell
pixi run ros2 topic hz /nokov/frame_number --window 300
```

运行约10秒后按 `Ctrl+C`。90 Hz相机的平均结果应接近：

```text
average rate: 89～91
```

当前版本的 `ros2 topic hz` 不支持 `--qos-reliability` 参数，不要在该命令后添加此参数。

### 3. 读取一帧带标签点

```powershell
pixi run ros2 topic echo /nokov/labeled_markers --once --timeout 10
```

### 4. 读取一帧刚体位姿

```powershell
pixi run ros2 topic echo /nokov/rigid_bodies --once --timeout 10
```

`--once` 表示收到一条消息后自动退出，`--timeout 10` 表示最多等待10秒。

## 八、安全停止顺序

1. 如果第二个终端仍在持续订阅，先按 `Ctrl+C` 停止订阅命令。
2. 在ROS桥接终端按 `Ctrl+C`，等待最终统计输出。
3. 如果正在直接采集，在采集终端按 `Ctrl+C`，等待 `Saved session folder` 和 `callback errors: 0`。
4. 确认所有数据文件已经保存后，再关闭XINGYING。
5. 按实验室设备要求关闭相机阵列/PoE交换机电源，最后断开网线和加密狗。

## 九、成功判据

一次完整数据通路测试至少应满足：

- XINGYING显示12台相机全部连接并能识别反光点。
- 直接采集脚本持续收到帧，停止时 `callback errors: 0`。
- 会话目录中的采集文件均存在且非空。
- `frame_no` 基本连续，平均频率约90 Hz。
- ROS桥接持续打印帧状态。
- 第二个ROS终端能发现 `/nokov/...` 话题。
- `/nokov/frame_number` 接收频率约90 Hz。
- `topic echo` 能读取实际点坐标或刚体位姿。

## 十、常见问题

### SDK连接失败

检查：

- 相机和交换机是否供电。
- 电脑是否连接正确的有线网卡。
- 有线网卡IPv4配置是否仍与相机网络匹配。
- XINGYING是否处于实时模式并开启SDK输出。
- 服务地址是否为 `10.1.1.198`。
- Windows防火墙是否阻止XINGYING或Python通信。

### 只能看到 `/rosout` 和 `/parameter_events`

通常表示桥接节点未运行、已经退出，或者终端没有处于同一ROS Domain。应从 `D:\ros2_jazzy` 使用 `pixi run ...`，以自动获得Domain ID 42和完整ROS环境。

### 出现 `topic ... does not appear to be published yet`

命令刚启动时ROS发现尚未完成可能短暂出现该警告。如果随后能持续显示频率或消息，则无需处理；如果一直没有数据，再检查桥接终端是否仍在发布。

### `topic hz` 报“不认识 `--qos-reliability`”

本机版本的 `topic hz` 没有该参数，直接使用：

```powershell
pixi run ros2 topic hz /nokov/frame_number --window 300
```

### 退出采集时出现关闭文件错误

迁移后的脚本已经修复SDK迟到回调与文件关闭之间的竞态。请确认运行的是：

```text
D:\Projects\nokov_hand\mocap\inspect_mocap.py
```

不要继续运行旧目录中的脚本副本。

## 十一、无硬件24点合成闭环

真实手部反光点设备到货前，可生成一份与当前NOKOV采集格式一致的24点合成会话，并从落盘后的 `points.csv` 反算6维归一化控制量：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m ml.synthetic_hand_pipeline
```

合成原始数据写入 `data/raw/synthetic/`，角度和6维结果写入 `data/processed/synthetic/`。这些数据用于验证程序链路，不是人体解剖真值，也不能直接发送给REVO2。

临时24点拓扑、6维通道、数学方法、输出字段和真实数据接入条件见 [`docs/synthetic_hand_pipeline.md`](docs/synthetic_hand_pipeline.md)。

生成后可按录制时间轴回放最新会话，同时显示24点动画、6维控制条和计算延迟：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion
```

## 迁移与备份说明

旧目录 `D:\GPTwork\hand_mocap` 当前仅作为备份和厂商SDK资料存放处。正式代码和后续实验数据均以 `D:\Projects\nokov_hand` 为准。旧目录暂不删除。
