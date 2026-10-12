# 动捕采集、处理与可视化流程

本文说明从 XINGYING/NOKOV SDK 获取动捕数据，到保存、处理、可视化的完整流程。

下面命令中的 `D:\Projects\nokov_hand` 和 `D:\venvs\nokov_hand` 是本机已验证的推荐路径；如果项目或虚拟环境放在其他位置，请同步替换命令中的路径。

## 1. 数据流

```text
XINGYING Live Mode
  -> NOKOV Python SDK
  -> mocap/inspect_mocap.py
  -> data/raw/mocap_YYYYMMDD_HHMMSS/
  -> ml/process_hand_sessions.py
  -> data/processed/mocap_YYYYMMDD_HHMMSS/
  -> ml/replay_hand_motion.py
```

## 2. 直接采集

推荐命令：

```powershell
Set-Location D:\Projects\nokov_hand

D:\venvs\nokov_hand\Scripts\python.exe .\mocap\inspect_mocap.py `
  --server 10.1.1.198 `
  --print-every 90 `
  --max-points 5 `
  --start-delay 3 `
  --duration 10
```

默认输出：

```text
data/raw/mocap_YYYYMMDD_HHMMSS/
├─ frames.csv.gz
├─ points.csv.gz
├─ skeleton_segments.csv.gz
├─ skeleton_descriptions.json.gz
└─ rigid_bodies.csv.gz
```

字段说明见 [../data/README.md](../data/README.md)。

## 3. 处理手部数据

处理最新 5段：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.process_hand_sessions --latest 5
```

处理指定采集：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.process_hand_sessions `
  D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS
```

处理结果：

```text
data/processed/mocap_YYYYMMDD_HHMMSS/
├─ controls_6d.csv
├─ controls_6d_stable.csv
├─ joint_angles.csv
├─ marker_layout.csv
├─ skeleton_segment_angles.csv
├─ skeleton_segment_summary.csv
└─ summary.json
```

## 4. 可视化回放

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.replay_hand_motion `
  --session D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS `
  --speed 0.5
```

窗口左侧显示 24点手部骨架，右侧显示 6维控制条。

## 5. 无硬件合成闭环

无硬件时可使用合成数据验证算法和文件格式：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m ml.synthetic_hand_pipeline
```

详细说明见 [synthetic_hand_pipeline.md](synthetic_hand_pipeline.md)。

## 6. 数据管理建议

GitHub 不保存 `data/raw/` 与 `data/processed/`。

实验数据应放在 NAS：

```text
/0-全体共享文件夹/2-仪器设备/度量光学三维动作捕捉系统/
└─ 动捕数据采集链路/
   └─ 实验数据/
      ├─ raw/
      └─ processed/
```

如果 NAS 已有既定目录，也可以沿用现有结构；关键是不要把大体积实验数据直接提交到 GitHub。
