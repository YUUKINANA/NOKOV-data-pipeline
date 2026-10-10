# 24点合成手部数据到6维输出的工程闭环

## 目的与边界

该闭环用于在真实手部反光点设备到货前，验证以下工程路径：

```text
24个三维点 → NOKOV同格式四文件 → 读取points.csv → 建立手掌局部坐标系
            → 计算手指分段夹角 → 压缩为6维归一化量 → 误差检查
```

它不是人体解剖模型，也不是REVO2控制协议。合成Marker编号、关节活动范围和6维通道均为临时工程约定，不能直接用于驱动真实灵巧手。

## 临时24点布局

- 1～4：手掌参考点，用于消除整只手的平移和旋转。
- 5～8：拇指MCP、PIP、DIP、指尖。
- 9～12：食指MCP、PIP、DIP、指尖。
- 13～16：中指MCP、PIP、DIP、指尖。
- 17～20：无名指MCP、PIP、DIP、指尖。
- 21～24：小指MCP、PIP、DIP、指尖。

每次运行都会在处理结果中生成 `marker_layout.csv`，保存Marker ID与语义名称的完整对应关系。

真实设备到货后，必须根据实际贴点说明和XINGYING资产定义替换这份映射，不能仅凭当前ID猜测人体关节。

## 临时6维输出

当前输出均限制在0～1：

1. `thumb_flexion`：拇指弯曲。
2. `thumb_opposition`：拇指对掌。
3. `index_flexion`：食指弯曲。
4. `middle_flexion`：中指弯曲。
5. `ring_flexion`：无名指弯曲。
6. `little_flexion`：小指弯曲。

这组通道只是根据“六路控制”作出的合理占位。拿到REVO2 SDK或协议后，应确认每一路的真实含义、方向、零点、范围、速度限制和安全边界。

## 几何计算方法

1. 用4个手掌点建立局部X、Y、Z坐标轴。
2. 将24点从XINGYING世界坐标变换到手掌局部坐标，去除整只手在场地内的平移和旋转。
3. 对每根手指的相邻骨段使用点积计算夹角：

   ```text
   angle = arccos((u · v) / (|u| |v|))
   ```

4. 将MCP、PIP、DIP的角度除以临时最大角度并求平均，得到每根手指0～1的弯曲量。
5. 拇指额外从掌平面内的方向角估计对掌量。

合成数据还会让整只手在世界坐标中移动和旋转，以验证结果依赖局部手型，而不是依赖手位于场地中的绝对位置。

## 运行方法

在PyCharm终端或PowerShell中运行：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m ml.synthetic_hand_pipeline
```

默认生成6秒、90 Hz、540帧数据，并为每个坐标加入标准差为0.15 mm的高斯噪声。可以调整：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.synthetic_hand_pipeline `
  --frames 900 `
  --fps 90 `
  --noise-mm 0.3 `
  --seed 42
```

## 输出结构

```text
data/raw/synthetic/mocap_YYYYMMDD_HHMMSS/
├─ raw.jsonl
├─ frames.csv
├─ points.csv
└─ rigid_bodies.csv

data/processed/synthetic/mocap_YYYYMMDD_HHMMSS/
├─ truth_6d.csv
├─ controls_6d.csv
├─ joint_angles.csv
├─ marker_layout.csv
└─ metrics.json
```

- `points.csv`严格沿用现有长表格式，并同时含有 `markerset` 与 `labeled_marker`。反算程序只读取后者，避免同一物理点被重复使用。
- `truth_6d.csv`是合成器生成动作时使用的真值。
- `controls_6d.csv`包含真值、几何估计值和绝对误差；以后真正发送给灵巧手的是 `command_*_0_1` 这6列经过硬件标定后的版本。
- `joint_angles.csv`保存各段夹角，便于检查角度计算。
- `metrics.json`汇总平均误差、最大误差和有效帧数。

原始与处理后的合成数据都被Git忽略；代码、测试和说明可以进入版本管理。

## 直观回放与延迟观察

先运行一次生成脚本，再执行：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion
```

回放程序默认选择最新的合成会话，并按原始1倍速度播放。窗口左侧显示24点和骨段连接，右侧显示实时6维控制条，底部显示：

- `geometry compute`：当前帧从24点计算6维输出所用时间。
- `playback lag`：当前帧相对于录制时间轴晚了多少。
- `file preload`：启动时读取整个 `points.csv` 所用的总时间。

终端约每90帧输出一次6维向量。回放结束后，延迟和逐帧6维结果保存为处理目录中的 `replay_latency.csv`。

可以指定会话或减慢播放：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion `
  --session D:\Projects\nokov_hand\data\raw\synthetic\mocap_YYYYMMDD_HHMMSS `
  --speed 0.5
```

若只想测计算与调度性能、不显示动画，可运行：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion --no-visual
```

图形刷新会占用时间，因此动画模式下的 `playback lag` 包含Matplotlib绘图开销；`geometry compute` 才是当前几何算法自身的耗时。未来实时控制还需要另外测量SDK接收、ROS发布、灵巧手通信和执行器响应。

## 真实数据接入前仍缺少的信息

1. 24个真实反光点与手掌、各指节的语义对应。
2. 点ID在遮挡、重新识别和跨会话时是否稳定。
3. REVO2六路控制量的真实定义和通信接口。
4. 每一路的开合极限、正负方向和安全速度。
5. 人手角度到机械手行程之间的标定关系。

拿到这些信息后，保留CSV读取、局部坐标系、缺点检查和6维输出框架，替换合成拓扑及临时角度范围即可。

## 与机器学习的关系

当前闭环采用可解释的几何计算，不需要训练模型。虽然可以用合成真值训练回归网络，但这种模型只会学习合成器自身的规则，不能证明它适用于真实人手。

更合理的顺序是：

1. 先用几何法建立可验证的基线。
2. 用真实数据检查噪声、遮挡和个体差异。
3. 如果几何法不足，再使用带同步6维标签的数据训练回归模型，用于校准、补点或提高鲁棒性。
