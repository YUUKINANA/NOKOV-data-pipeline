# REVO2 Control Notes

本文记录当前阶段的 REVO2 灵巧手控制链路。目标是先用官方
`bc-stark-sdk` 跑通最小控制：把 6 个 `0..1000` 的位置控制量发送到
REVO2，再逐步接入 NOKOV/XINGYING 动捕处理结果。

## 当前状态

已在 Windows 上验证：

- 串口：`COM3`
- 波特率：`460800`
- 设备 ID：`127`
- Python 环境：`D:\venvs\nokov_hand`
- SDK 包：`bc-stark-sdk`
- 单次发送能驱动灵巧手动作。
- `get_device_info()`、`get_motor_status()`、部分 `get_finger_positions()`
  读取会偶发 `BrokenPipe`。目前发送控制量本身可用，读回状态不稳定。

运行 Python 脚本前，先完全退出强脑官方桌面软件。串口通常只能被一个
程序占用。

## 6 维控制顺序

当前项目统一使用以下顺序：

```text
[拇指弯曲, 拇指辅助/侧摆, 食指, 中指, 无名指, 小指]
```

数值范围为 `0..1000`：

- `0`：打开
- `1000`：闭合

实验阶段不要直接发送大幅度指令。建议从 `50..300` 开始，确认方向和动作
范围后再逐步提高。

## 单次控制

脚本：

```text
D:\Projects\nokov_hand\revo2\send_positions.py
```

查看状态：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions status
```

这个命令会尝试逐项读取设备信息、单位模式、当前位置和电机状态。只要
`read finger unit mode` 或 `read finger positions` 能成功，就说明基础通信
大概率是通的。

发送 6 维位置：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions send 400 399 120 50 50 49 --speed 100
```

张开：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.send_positions open --speed 100
```

常用参数：

- `--speed 100`：给所有手指设置同一个速度，范围 `0..1000`。
- `--speeds a b c d e f`：给 6 个通道分别设置速度。
- `--readback`：发送后读取当前位置。当前读回偶发不稳定，非必要不建议加。
- `--verify-info`：发送前读取设备信息。当前该读取不稳定，非必要不建议加。

## 素材回放

脚本：

```text
D:\Projects\nokov_hand\revo2\replay_positions.py
```

输入是 `ml.process_hand_sessions` 生成的：

```text
data/processed/mocap_.../controls_6d_stable.csv
```

当前默认回放策略：

- 默认读取最新的 `data/processed/mocap_*/controls_6d_stable.csv`。
- 默认回放全部 6 个通道：拇指弯曲、拇指辅助/侧摆、食指、中指、无名指、小指。
- 默认发送频率 `15 Hz`。
- 默认速度 `250`。
- 默认最大指令限幅到 `500`。
- 默认单次发送最大变化量 `35`，减少跳变。

先做 dry-run，不打开串口：

```powershell
Set-Location D:\Projects\nokov_hand
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --dry-run --rate-hz 15 --speed 250 --max-position 500
```

确认摘要没问题后，正式回放：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --rate-hz 15 --speed 250 --max-position 500
```

如果暂时不想让拇指参与回放，可以回到四指模式：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --hold-thumb --rate-hz 15 --speed 250 --max-position 500
```

如果动作幅度太小：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --rate-hz 15 --speed 250 --max-position 700
```

如果动作明显跟不上，可先提高速度：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --rate-hz 15 --speed 300 --max-position 500
```

如果动作一顿一顿，再尝试提高发送频率：

```powershell
D:\venvs\nokov_hand\Scripts\python.exe -m revo2.replay_positions --rate-hz 20 --speed 250 --max-position 500
```

不建议一开始超过 `20 Hz`。动捕原始频率约 `90 Hz`，但灵巧手和串口链路
不需要吃这么密的指令。过高频率更容易造成通信拥堵、动作抖动或日志噪声。

## 安全规则

硬件回放前建议依次确认：

1. 灵巧手电量充足。
2. 官方桌面软件已经退出。
3. 手指周围没有硬物、线缆或人体遮挡。
4. 首次测试使用 `--max-position 300..500`。
5. 首次测试使用 `--speed 100..250`。
6. 首次打开拇指回放时，建议仍保留 `--max-position 500`，确认方向和幅度合理后再提高。
7. 手放在容易观察、能立刻断电的位置。
8. 如有异常，先按 `Ctrl+C` 停止脚本，再执行 `open --speed 100`。

## 已知现象

当前 SDK/固件组合下，以下读取可能失败：

```text
get_device_info()
get_motor_status()
get_finger_positions()
```

错误常见形式：

```text
Transport(Kind(BrokenPipe))
Transport(Custom { kind: Other, error: "bytes remaining on stream" })
```

如果动作已经执行，而只有读回失败，可以先作为通信日志噪声处理。若发送
指令本身失败、动作明显失控、或连续多次无法打开串口，则应停止实验，检查：

- 官方桌面软件是否仍占用串口。
- 端口是否仍为 `COM3`。
- 波特率是否仍为 `460800`。
- 设备 ID 是否仍为 `127`。
- USB-RS485 转接器是否松动。

## 数据流位置

当前离线复现链路是：

```text
data/raw/mocap_...
  -> ml.process_hand_sessions
  -> data/processed/mocap_.../controls_6d_stable.csv
  -> revo2.replay_positions
  -> REVO2
```

未来实时链路会把中间的 CSV 替换成实时队列：

```text
NOKOV SDK
  -> 24 点手部姿态计算
  -> 6 维控制量
  -> 限幅/限速/滤波
  -> REVO2
```

## 实时动捕复现

脚本：

```text
D:\Projects\nokov_hand\revo2\live_mocap_control.py
```

这条链路把 NOKOV/XINGYING SDK 收到的实时帧直接接入现有的24点手部计算和REVO2发送逻辑：

```text
XINGYING实时识别
  -> NOKOV SDK回调
  -> 24点手部坐标，自动识别左/右手ID偏移
  -> StableHandControlFilter短时丢点补偿、平滑、限速
  -> 6维0..1控制量
  -> 0..1000 REVO2位置指令限幅/限跳变
  -> 可选发送到REVO2
```

默认不打开串口，只实时打印计算结果：

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

确认终端中的 `visible=.../24`、`controls=[...]` 和 `pos=[...]` 随手部动作变化合理后，再正式打开灵巧手输出：

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

常用参数：

- `--enable-hand`：真正打开COM口并发送到REVO2。不加这个参数时只是dry-run。
- `--rate-hz 15`：每秒最多发送15次控制指令。先保持15 Hz，确认稳定后再考虑20 Hz。
- `--speed 250`：REVO2动作速度。此前离线回放中250比较合适。
- `--max-position 500`：把所有通道限制在0..500，避免首次实时控制幅度过大。
- `--max-step 35`：每次发送最多变化35个单位，抑制突然跳变。
- `--hold-s 0.25`：某些点短时间丢失时，最多用上一帧位置顶住0.25秒。
- `--smooth-alpha 0.35`：平滑系数；越小越稳但延迟越明显。
- `--max-rate-per-s 3.0`：6维归一化控制量的内部限速。
- `--output-deadband 10`：最终0..1000指令变化小于10时不发送，减少机械抖动；填 `0` 可关闭。
- `--output-quantum 5`：最终指令按5个单位取整，避免把坐标噪声原样传给电机；填 `1` 可关闭。
- `--output-alpha 0.6`：最终0..1000指令再做一次平滑；越小越稳但响应越慢，填 `1` 可关闭。
- `--min-confidence 0.15`：低置信度时冻结输出，避免丢点造成突然跳变。
- `--keepalive-s 0`：默认不重复发送无变化指令。如后续发现REVO2需要保活，可设置为 `1..2` 秒。
- `--hold-thumb`：先只驱动食指、中指、无名指、小指，两个拇指通道保持不动。
- `--record`：实时驱动的同时，在 `data/raw/mocap_...` 保存一份原始采集数据。
- `--duration 10`：只运行10秒后自动停止；默认 `0` 表示一直运行到 `Ctrl+C`。
- `--open-on-exit`：退出前发送一次全张开 `[0,0,0,0,0,0]`。只有确认安全时再使用。

首次实时驱动建议顺序：

1. 只运行dry-run，确认能稳定看到 `visible=24/24` 或短时丢点补偿信息。
2. 保持 `--max-position 300..500`，加 `--enable-hand` 做短时间测试。
3. 如果方向正确但幅度小，再逐步提高 `--max-position`。
4. 如果动作抖动，先提高 `--output-deadband` 到 `15..25`，或把 `--output-quantum` 提高到 `10..20`。
5. 如果仍抖动，再降低 `--rate-hz` 或 `--output-alpha`，不要先提高速度。
6. 如果动作太迟钝，再反向调小 `--output-deadband`、调大 `--output-alpha`，或小幅提高 `--rate-hz`。
7. 如果 `max-position` 调高后仍抓不紧，先用 `revo2.send_positions` 单独测试固定位置，区分是映射问题还是REVO2执行参数问题。
8. 如需留实验素材，加 `--record`，但实时调参阶段可以先不保存。

### 机械安全输出层

实时程序里现在有两层稳定机制：

第一层在 `StableHandControlFilter`：处理24点坐标、短时丢点、6维归一化控制量平滑和限速。

第二层在 `MechanicalSafetyOutputLayer`：只处理最后要给REVO2的 `0..1000` 位置指令。它不改变手部几何算法，只负责让真实机械少吃噪声：

```text
候选位置指令
  -> 低置信度冻结
  -> 量化
  -> 输出平滑
  -> 死区判断
  -> 允许发送 / 不发送
```

终端输出中：

- `target=[...]`：本帧计算出的候选REVO2指令。
- `output=[...]`：经过机械安全层后的最终安全指令。
- `action=first_output`：第一条有效输出。
- `action=changed`：变化足够大，允许发送。
- `action=deadband`：变化太小，被死区抑制，不发送。
- `action=low_confidence`：点位置信心不足，冻结上一条安全指令。
