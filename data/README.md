# NOKOV 数据目录与字段说明

本文档对应 `mocap/inspect_mocap.py` 当前生成的数据格式。每运行一次采集脚本，都会在 `data/raw/` 下创建一个独立的时间戳文件夹。

```text
data/
├─ README.md
├─ raw/
│  ├─ mocap_20260903_135001/
│  │  ├─ frames.csv.gz
│  │  ├─ points.csv.gz
│  │  ├─ skeleton_segments.csv.gz
│  │  ├─ skeleton_descriptions.json.gz
│  │  └─ rigid_bodies.csv.gz
│  └─ legacy/
└─ processed/
   └─ legacy/
```

文件夹名格式为 `mocap_YYYYMMDD_HHMMSS`。如果同一秒内重复创建，会自动追加 `_02`、`_03` 等后缀。

当前默认采集策略是“手部训练友好模式”：`--save-mode hand` 且结束后自动压缩。它保留后续训练/控制最需要的数据，同时避免默认生成体积较大的 `raw.jsonl`。如果要排查SDK原始结构，可临时使用 `--save-mode full`；如果要人工打开未压缩CSV，可临时加 `--no-compress-on-finish`。

## 原始文件分别用于什么

| 文件 | 每行代表什么 | 推荐用途 |
| --- | --- | --- |
| `frames.csv` | 一个SDK源帧的摘要 | 检查帧率、时长、延迟、丢帧和每帧对象数量 |
| `points.csv` | 某一帧中的一个三维点 | 分析反光点轨迹、速度、缺失和后续机器学习 |
| `skeleton_segments.csv` | 某一帧中的一个XINGYING骨骼段 | 分析模板解算后的骨段位置、姿态和相对角度 |
| `skeleton_descriptions.json` | 一次采集对应的XINGYING模板描述 | 保存骨骼名称、骨段名称、ID和父子关系 |
| `rigid_bodies.csv` | 某一帧中的一个刚体 | 分析刚体位置、旋转、跟踪质量以及机器人位姿 |
| `raw.jsonl` | 一个完整的SDK源帧 | 仅 `--save-mode full` 生成；用于调试和以后重新解析SDK嵌套字段 |

CSV文件使用带BOM的UTF-8编码，通常可以直接使用Excel打开。数据量较大时推荐使用Pandas，不建议用Excel进行大量逐帧运算。使用 `--compress-on-finish` 采集时，这些文本文件会以 `.gz` 无损压缩保存；项目处理脚本可以直接读取，不需要手动解压。

## 公共时间与索引字段

这些字段出现在多个文件中，可用于在文件之间关联同一帧。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `sample_index` | 整数 | 当前采集会话内的样本序号，从1开始；最适合在不同CSV之间连接数据 |
| `frame_no` / JSON中的`frame` | 整数 | XINGYING/NOKOV SDK给出的源帧号；通常连续递增，但不保证从0或1开始 |
| `timestamp_ms` | 整数 | SDK提供的帧时间戳，脚本按毫秒保存 |
| `elapsed_s` | 浮点数 | 相对本次采集第一帧的时间，单位秒；第一帧通常为0 |

建议优先使用 `sample_index` 对齐文件，使用 `frame_no` 检查是否丢帧，使用 `elapsed_s` 绘制随时间变化的曲线。

## `frames.csv`

一行对应一个接收到的SDK源帧。它不保存具体坐标，只保存该帧的总体情况。

| 字段 | 单位 | 含义 |
| --- | --- | --- |
| `sample_index` | — | 会话内样本序号 |
| `frame_no` | — | SDK源帧号 |
| `timestamp_ms` | ms | SDK帧时间戳 |
| `elapsed_s` | s | 从本次采集第一帧开始经过的时间 |
| `latency_ms` | ms | SDK报告的当前帧延迟；这是当前脚本对 `fLatency` 的单位解释 |
| `marker_sets` | 个 | 当前帧中的标记点集合数量 |
| `labeled_markers` | 个 | 当前帧中带SDK标签/ID的反光点数量 |
| `unidentified_markers` | 个 | 当前帧中未识别、未归属的反光点数量 |
| `rigid_bodies` | 个 | 当前帧中的刚体数量 |
| `skeletons` | 个 | 当前帧中的骨骼数量 |
| `analog_channels` | 个 | 当前帧中的模拟量通道数量 |

常用检查：

- 采集帧数：CSV数据行数。
- 采集时长：最后一行 `elapsed_s`。
- 实际平均帧率：`(总帧数 - 1) / (最后elapsed_s - 第一elapsed_s)`。
- 源帧是否连续：相邻 `frame_no` 的差通常应为1。
- 跟踪是否稳定：观察 `labeled_markers` 和 `rigid_bodies` 是否频繁变化。

## `points.csv`

这是反光点数据的“长表”：一行只保存一个点，而不是一整帧。一个帧通常对应多行。

| 字段 | 单位 | 含义 |
| --- | --- | --- |
| `sample_index` | — | 所属帧的会话内样本序号 |
| `frame_no` | — | 所属SDK源帧号 |
| `timestamp_ms` | ms | 所属帧的SDK时间戳 |
| `elapsed_s` | s | 所属帧相对采集起点的时间 |
| `category` | — | 点的类别，见下表 |
| `group_name` | — | 标记点集合名称；仅 `markerset` 通常有值 |
| `point_id_or_index` | — | 点的SDK ID或当前集合/数组中的索引，具体含义取决于 `category` |
| `x_mm` | mm | 点在标定坐标系中的X坐标 |
| `y_mm` | mm | 点在标定坐标系中的Y坐标 |
| `z_mm` | mm | 点在标定坐标系中的Z坐标 |
| `valid` | 0/1 | 1表示三个坐标均为有限且未使用SDK丢点哨兵值；0表示当前记录无效 |
| `size_mm` | mm | SDK报告的标记点尺寸；当前仅 `labeled_marker` 填写，其余类别留空 |

### `category` 的三种取值

| `category` | 来源 | `point_id_or_index` 的含义 | 身份稳定性 |
| --- | --- | --- | --- |
| `markerset` | 某个Marker Set中的点 | 该点在集合内的索引 | 取决于XINGYING场景资产和Marker Set配置 |
| `labeled_marker` | SDK已标记点列表 | SDK提供的Marker ID | 通常最适合追踪同一物理点，但仍应通过实验确认ID稳定性 |
| `unidentified_marker` | SDK未识别点列表 | 该点在当前帧数组内的索引 | 不应认为跨帧稳定，同一索引下一帧可能代表另一个物理点 |

重要：同一个物理反光点可能同时出现在 `markerset` 和 `labeled_marker` 两类记录中。因此，`points.csv` 的总行数不等于现场反光点数量。用于轨迹或训练时，应先明确只选择一种 `category`，通常优先考虑 `labeled_marker`。

右手采集时，XINGYING 可能把 `labeled_marker` 的SDK点号保存为 `25..48`，而手部贴点表格的语义编号仍是 `1..24`。当前处理脚本会自动检测这种偏移，并在 `data/processed/.../summary.json` 中写入 `input_marker_id_offset`。例如 `input_marker_id_offset = 24` 表示原始SDK点号 `25..48` 已在处理阶段映射回语义点号 `1..24`。

某个点暂时不可见时，可能表现为：

- 该帧没有该点对应的行；或
- 仍有一行，但 `valid=0`。

后续预处理必须按 `sample_index + category + point_id_or_index` 检查缺失，不能假设每帧总有固定行数。

## `rigid_bodies.csv`

一行对应某一帧中的一个刚体。如果一帧有多个刚体，同一个 `sample_index` 会出现多行。

| 字段 | 单位 | 含义 |
| --- | --- | --- |
| `sample_index` | — | 所属帧的会话内样本序号 |
| `frame_no` | — | 所属SDK源帧号 |
| `timestamp_ms` | ms | 所属帧的SDK时间戳 |
| `elapsed_s` | s | 相对本次采集第一帧的时间 |
| `rigid_id` | — | XINGYING/NOKOV中的刚体ID |
| `x_mm`、`y_mm`、`z_mm` | mm | 刚体原点在标定坐标系中的位置 |
| `qx`、`qy`、`qz`、`qw` | — | 刚体姿态四元数，顺序为 `(x, y, z, w)` |
| `marker_count` | 个 | SDK报告的该刚体标记点数量 |
| `mean_error` | SDK定义 | 刚体拟合平均误差；通常越小表示拟合越好，精确单位以厂商SDK文档为准 |
| `params` | 位字段/整数 | SDK提供的刚体状态参数；精确位含义以当前版本厂商SDK文档为准 |

`rigid_bodies.csv` 当前没有独立的 `valid` 字段。使用刚体数据时，应同时检查坐标和四元数是否有限，并结合 `params`、`marker_count` 与 `mean_error` 判断跟踪质量。

四元数不是欧拉角。如果后续需要滚转、俯仰、偏航角，应统一约定坐标轴和旋转顺序后再转换，避免不同软件采用不同约定。

## `skeleton_segments.csv`

一行对应某一帧中的一个 XINGYING skeleton segment。它来自 XINGYING 模板解算结果，不是我们自己用散点连出来的手部模型。

| 字段 | 单位 | 含义 |
| --- | --- | --- |
| `sample_index` | — | 所属帧的会话内样本序号 |
| `frame_no` | — | 所属SDK源帧号 |
| `timestamp_ms` | ms | 所属帧的SDK时间戳 |
| `elapsed_s` | s | 相对本次采集第一帧的时间 |
| `skeleton_id` | — | XINGYING/NOKOV中的骨骼ID |
| `segment_index` | — | 该segment在当前skeleton数组中的索引 |
| `segment_id` | — | XINGYING/NOKOV中的segment ID |
| `x_mm`、`y_mm`、`z_mm` | mm | segment原点在标定坐标系中的位置 |
| `qx`、`qy`、`qz`、`qw` | — | segment姿态四元数，顺序为 `(x, y, z, w)` |
| `marker_count` | 个 | SDK报告的该segment关联的标记点数量 |
| `mean_error` | SDK定义 | segment拟合误差；精确单位以厂商SDK文档为准 |
| `params` | 位字段/整数 | SDK提供的segment状态参数 |
| `marker_ids` | — | 该segment关联的marker ID列表，用分号分隔 |

新录制会跳过位置或四元数为 `9999999` 等无效值的骨骼段，因此未出现在场景中的模板不会逐帧写入占位行。`frames.csv` 仍保留每个源帧，`skeleton_descriptions.json` 仍保留模板名称与层级；某帧缺少一个预期的骨骼段即表示该段没有有效位姿。不要仅凭 `marker_count` 判断有效性：未出现的模板也可能报告非零关联点数。旧录制中的无效占位行不会被修改，但手部处理程序在计算骨骼角度前会过滤它们。

如果该文件存在，`ml/process_hand_sessions.py` 会额外生成：

- `skeleton_segment_summary.csv`：每个segment的名称、父级ID和出现帧数。
- `skeleton_segment_angles.csv`：每帧中子segment相对父segment的姿态夹角。

这一步是后续“复用XINGYING人体/手部模板”的基础。具体如何从这些segment映射到REVO2的6维控制量，需要先看下一次真实采集保存出来的 `skeleton_descriptions.json` 中的segment命名和父子关系。

## `raw.jsonl`

JSONL表示“每一行都是一个完整JSON对象”。它不是一个外层带方括号的JSON数组，因此适合边采集边追加，也能在意外中断时保留已经写完的帧。

每行的顶层结构为：

```text
sample_index
elapsed_s
frame
timestamp_ms
latency
counts
marker_sets
labeled_markers
unidentified_markers
rigid_bodies
skeletons
```

主要嵌套对象：

- `counts`：与 `frames.csv` 中的数量字段对应。
- `marker_sets[]`：包含 `name`、`marker_count`、`visible_count` 和 `markers[]`。
- `marker_sets[].markers[]`：包含集合内 `index`、`xyz_mm`、`valid`。
- `labeled_markers[]`：包含 `id`、`xyz_mm`、`size`、`valid`。
- `unidentified_markers[]`：包含帧内 `index`、`xyz_mm`、`valid`。
- `rigid_bodies[]`：包含 `id`、`position_mm`、`orientation_xyzw`、`marker_count`、`mean_error`、`params`。
- `skeletons[]`：包含 `skeleton_id`、segment位置、segment四元数、关联marker ID、拟合误差和状态参数。

`raw.jsonl` 是信息最完整的原始记录，但文件体积较大。当前不建议日常训练采集默认保存它；只有在排查SDK字段、怀疑CSV字段不足，或准备扩展解析逻辑时再用 `--save-mode full`。

## 坐标系与ROS单位

- 文件中的位置统一保存为毫米（mm）。
- X、Y、Z轴的实际方向和原点由XINGYING工程的标定与设定决定，应以软件3D视图中的坐标轴为准。
- 不同日期重新标定或重设原点后，坐标不能直接混合训练，除非先完成坐标对齐或归一化。
- ROS 2桥接脚本会把位置从毫米转换为米，并将 `frame_id` 设置为 `nokov_world`。

## 推荐的数据处理原则

1. `data/raw/` 只保存原始采集结果，不直接手工修改。
2. 清洗、补点、滤波和重采样结果写入 `data/processed/`。
3. 每个手势使用独立标签文件夹，例如 `data/raw/ok/`、`data/raw/gun/`；时间戳会话文件夹作为一次独立样本。
4. 建模前确认Marker ID在跨帧和跨会话中是否代表同一物理反光点。
5. 划分训练集和测试集时按“采集会话”划分，不要把同一次连续采集的相邻帧随机拆到两边，否则容易产生数据泄漏。
6. 记录每次采集使用的标定文件、Marker布局、采样频率和动作说明；这些信息变化可能比模型参数更影响结果。

## Pandas读取示例

下面的路径只是示例。实际使用时，把 `session_dir` 改成你自己的某一次采集目录即可，例如项目下的 `data/raw/mocap_YYYYMMDD_HHMMSS`。

```python
from pathlib import Path

import pandas as pd

session_dir: Path = Path(r"D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS")

# 默认采集会生成 .gz；pandas 可以直接读取。
frames = pd.read_csv(str(session_dir / "frames.csv.gz"))
points = pd.read_csv(str(session_dir / "points.csv.gz"))
rigid_bodies = pd.read_csv(str(session_dir / "rigid_bodies.csv.gz"))

# 只保留有效且带稳定SDK标签的点
labeled = points[
    (points["category"] == "labeled_marker") & (points["valid"] == 1)
].copy()

print(frames.head())
print(labeled.head())
print(rigid_bodies.head())
```

读取压缩CSV示例：

```python
from pathlib import Path

import pandas as pd

session_dir: Path = Path(r"D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS")

# pandas 可以直接读取 .gz；如果你用了 --no-compress-on-finish，把 .gz 去掉即可。
frames = pd.read_csv(str(session_dir / "frames.csv.gz"))
points = pd.read_csv(str(session_dir / "points.csv.gz"))
```

读取 `--save-mode full` 生成的JSONL示例：

```python
from pathlib import Path

import pandas as pd

session_dir: Path = Path(r"D:\Projects\nokov_hand\data\raw\mocap_YYYYMMDD_HHMMSS")
raw_frames = pd.read_json(str(session_dir / "raw.jsonl"), lines=True)
print(raw_frames.columns)
```

## 无硬件合成数据

`ml.synthetic_hand_pipeline` 会在以下目录生成一组明确标记为synthetic的测试数据：

```text
data/raw/synthetic/mocap_YYYYMMDD_HHMMSS/
data/processed/synthetic/mocap_YYYYMMDD_HHMMSS/
```

原始目录仍使用本文档定义的 `frames.csv`、`points.csv` 等采集格式；合成数据通常不包含真实 XINGYING skeleton。处理目录额外包含：

| 文件 | 用途 |
| --- | --- |
| `truth_6d.csv` | 合成器生成动作时使用的6维真值 |
| `controls_6d.csv` | 从落盘后的 `points.csv` 反算的6维结果及误差 |
| `joint_angles.csv` | 由相邻骨段计算的诊断角度，单位度 |
| `marker_layout.csv` | 临时24点ID与语义名称的对应关系 |
| `metrics.json` | 有效帧数和误差汇总 |

该数据只用于验证格式与算法闭环，不得与真实实验数据混合作为训练集。详细说明见 `docs/synthetic_hand_pipeline.md`。
