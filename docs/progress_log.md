# 项目进展记录

## 2026-10-10

### GitHub/NAS 发布整理

- 确认项目中文名称为“动捕数据采集链路”，GitHub 私有仓库为 `YUUKINANA/NOKOV-data-pipeline`。
- 将 README 顶部改为面向导师和同学复现的中文总览，并明确项目分为三个阶段：动捕驱动灵巧手实时复现、家庭服务机器人示教数据采集系统、面向机械臂+灵巧手的模仿学习前期平台。
- 新增 `docs/setup_windows.md`、`docs/hardware_setup.md`、`docs/mocap_pipeline.md`、`docs/live_control.md`、`docs/ml_plan.md`、`docs/github_nas_publish.md`。
- 补强 `.gitignore`，排除实验数据、模型、厂商SDK、License、压缩包和演示视频，避免误传到 GitHub。
- 明确 GitHub 只保存代码和文档；NAS 保存厂商资料、License、实验数据、模型、视频和完整备份。

## 2026-09-08

### REVO2控制链路

- 清理临时环境和缓存：`D:\Projects\example_revo2\.venv`、`D:\venvs\base`、`D:\venvs\pip_cache`、主项目内临时复制的 `example_revo2` 片段。
- 保留正式项目 `D:\Projects\nokov_hand`、主虚拟环境 `D:\venvs\nokov_hand`、学长参考源码 `D:\Projects\example_revo2`。
- 新增 `revo2/send_positions.py`：基于官方 `bc-stark-sdk` 的最小6维位置发送脚本。
- 新增 `revo2/replay_positions.py`：读取 `controls_6d_stable.csv`，按时间轴把处理后的6维序列回放到REVO2。
- 当前已验证硬件参数：`COM3`、`460800`、`slave_id=127`。
- 单次发送已能稳定驱动灵巧手动作；当前 `get_device_info()`、`get_motor_status()` 和部分读回状态接口会偶发 `BrokenPipe`，暂不作为控制链路阻塞项。
- 回放脚本已从四指模式升级为默认6维全通道回放；如需回到四指模式，可使用 `--hold-thumb`。默认发送频率 `15 Hz`、速度 `250`、限幅 `500`、单次跳变限制 `35`。
- 新增 `revo2/live_mocap_control.py`：实时接收XINGYING/NOKOV帧，计算24点手部6维控制量，并可选发送到REVO2。默认dry-run，只有加 `--enable-hand` 才会打开串口。
- 实时脚本支持短时丢点保持、平滑、6维限速、REVO2位置限幅、单次跳变限制、固定发送频率和可选实时原始数据保存。
- 根据首次实时测试反馈，新增机械安全输出层：最终位置指令死区、量化、输出平滑、低置信度冻结和可选keepalive，减少频繁微小变化造成的灵巧手抖动。
- 新增 `docs/revo2_control.md`，记录命令、参数、安全规则、已知通信现象和离线/实时数据流。

### 验证结果

- 离线语法检查通过：`revo2/send_positions.py`、`revo2/replay_positions.py`、关键 `ml` 处理脚本。
- 离线测试通过：`tests/test_synthetic_hand_pipeline.py`、`tests/test_process_hand_sessions.py`、`tests/test_replay_hand_motion.py`，共6项。
- 使用 `mocap_20260907_143807` 的 `controls_6d_stable.csv` 做dry-run：约5秒素材在 `15 Hz` 下生成71帧回放指令。
- 实时控制新增单元测试4项，覆盖右手ID偏移、0..1到0..1000映射、拇指保持、单帧缓冲覆盖策略；当前全项目12项测试通过。
- 机械安全输出层新增单元测试3项，覆盖死区抑制、量化+输出平滑、低置信度冻结；实时控制测试共7项通过。

### 后续待办

1. 用户返回后，先运行 `revo2.live_mocap_control` 的dry-run，确认实时6维控制量变化正常。
2. 再加 `--enable-hand` 做低幅度实时复现测试，初始建议 `--rate-hz 15 --speed 250 --max-position 500 --max-step 35 --output-deadband 10 --output-quantum 5 --output-alpha 0.6`。
3. 若仍抖动，优先调大 `--output-deadband` 和 `--output-quantum`；若太迟钝，再反向调小并提高 `--output-alpha`。
4. 记录不同 `--speed`、`--rate-hz`、`--max-position` 参数下的跟随效果和日志稳定性。
5. 若读回状态长期不稳定，再评估是否需要固定SDK版本、降低读取频率或完全移除非必要读回。
6. 确认拇指两个通道方向和幅度后，再逐步放宽 `--max-position`。

## 2026-09-03

### 项目与环境

- 正式开发目录已确定为 `D:\Projects\nokov_hand`；旧目录仅保留备份与厂商资料。
- 普通采集/数据处理/机器学习环境继续使用 `D:\venvs\nokov_hand`（Python 3.11）。
- ROS 2 Jazzy继续使用 `D:\ros2_jazzy` 的Pixi环境（Python 3.12），两个环境保持隔离。
- 初始化本地Git仓库和 `main` 分支，未连接任何远端仓库。
- 补强 `.gitignore`，排除原始与处理数据、模型、IDE缓存、厂商二进制文件、License和凭据。
- 在PyCharm中配置Codex附带的Git 2.53.0，使版本状态和提交历史可以正常显示。

### 实际采集数据核对

- 阅读并核对迁移后的项目说明和 `data/README.md`。
- 检查 `mocap_20260903_134301` 三点刚体测试会话：约20.5秒、1846帧、约90 Hz，源帧连续。
- 明确同一物理点会同时出现在 `markerset` 与 `labeled_marker` 中；后续算法优先使用后者，避免重复计数。
- 该三点会话仅用于验证采集链路，不作为手部动作或机器学习数据。

### 24点到6维合成闭环

- 新增临时24点手部拓扑：4个手掌参考点，加上每根手指4个关节点。
- 新增6维占位输出：拇指弯曲、拇指对掌、食指/中指/无名指/小指弯曲。
- 合成器通过正向运动学生成连续动作，同时加入整手平移、旋转和0.15 mm坐标噪声。
- 合成数据沿用真实采集的四文件格式，并明确保存在 `data/raw/synthetic/`。
- 处理程序重新读取落盘后的 `points.csv`，筛选 `labeled_marker`，建立手掌局部坐标系，计算各骨段夹角并输出6维归一化量。
- 处理结果写入 `data/processed/synthetic/`，包括真值、6维命令、诊断角度、Marker布局和误差指标。
- 默认测试为6秒、90 Hz、540帧；总体平均绝对误差为0.003741，最大绝对误差为0.023640。

### 离线复现与延迟

- 新增按原始时间轴回放的可视化程序：左侧显示24点手部运动，右侧显示实时6维控制条。
- 回放过程逐帧执行“读取坐标 → 计算角度 → 输出6维量”，并记录文件加载、几何计算和调度延迟。
- 1倍速、无绘图性能基线：540帧加载约80.9 ms；单帧几何计算平均0.414 ms、最大0.839 ms；调度延迟平均0.319 ms、最大0.834 ms。
- 90 Hz对应单帧预算约11.11 ms，因此当前几何计算具有充足余量。
- 当前尚未测量真实SDK、ROS 2传输、灵巧手通信和执行器机械响应的端到端延迟。

### 验证结果

- 新增24点布局、全局位姿不变性和文件闭环测试。
- 项目自动化测试结果：4项全部通过。
- 合成数据只用于工程闭环验证，不作为真实人体训练数据，也不能直接作为REVO2电机命令。

### 后续待办

1. 手部反光点设备到货后确认真实24点贴点拓扑、Marker ID稳定性和遮挡行为。
2. 获取REVO2六路控制定义、SDK/通信协议、范围、方向和安全限制。
3. 用真实张手、握拳及分指动作完成个体标定，替换当前临时拓扑和角度范围。
4. 测量“相机采集 → SDK → 角度计算 → 通信 → 灵巧手响应”的端到端延迟。
5. 几何基线验证后，再决定是否需要用同步6维标签训练回归模型。
