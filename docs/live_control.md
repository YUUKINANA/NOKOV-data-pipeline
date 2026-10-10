# 实时动作复现链路

本文说明如何使用 NOKOV/XINGYING 实时动捕数据驱动 REVO2 灵巧手。

## 1. 实时数据流

```text
XINGYING Live Mode
  -> NOKOV SDK callback
  -> 24点手部 marker
  -> 手掌局部坐标系
  -> 几何估计 6维控制量
  -> StableHandControlFilter
  -> MechanicalSafetyOutputLayer
  -> REVO2 0..1000 位置指令
```

其中：

- `StableHandControlFilter` 处理短时丢点、6维控制量平滑和归一化限速。
- `MechanicalSafetyOutputLayer` 处理真实机械输出前的死区、量化、平滑、低置信度冻结。

## 2. Dry-run

第一次运行必须先 dry-run，不打开串口：

```powershell
Set-Location D:\Projects\nokov_hand

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

观察终端中的：

- `visible=.../24`：当前帧有效手部点数量。
- `conf=...`：估计置信度。
- `target=[...]`：几何和滤波后的候选指令。
- `output=[...]`：机械安全层后的最终指令。
- `action=...`：本帧是否发送，或因死区/低置信度被冻结。

## 3. 正式驱动 REVO2

确认 dry-run 合理后加 `--enable-hand`：

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

如果想实时驱动时同时保存原始动捕数据：

```powershell
--record
```

如果暂时不驱动拇指：

```powershell
--hold-thumb
```

## 4. 参数调节

推荐初始参数：

```text
rate-hz: 15
speed: 250
max-position: 500
max-step: 35
output-deadband: 10
output-quantum: 5
output-alpha: 0.6
min-confidence: 0.15
```

如果灵巧手抖动：

```powershell
--output-deadband 20 --output-quantum 10
```

如果动作太迟钝：

```powershell
--output-deadband 5 --output-alpha 0.8
```

如果高幅度抓握不足：

1. 先确认终端 `target` 或 `output` 是否已经接近 `max-position`。
2. 如果输出本身不高，优先检查 24点到6维映射。
3. 如果输出已经很高但手不动，优先检查 REVO2 速度、力矩、机械阻力或电量。

## 5. 安全规则

正式驱动前必须确认：

1. REVO2 电量充足。
2. 官方桌面软件已退出。
3. 串口号正确，当前为 `COM3`。
4. 灵巧手周围没有硬物或人体遮挡。
5. 第一次测试使用 `--max-position 300..500`。
6. 如出现异常，先 `Ctrl+C` 停止脚本，再执行张开命令。

张开：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions open --speed 100
```

