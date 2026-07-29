# 2026 校赛数学建模：国际油价预测与中国经济韧性

本仓库用于按全国大学生数学建模竞赛要求完成校赛 A 题“国际油价预测建模”。研究主线为：

> 美伊冲突与霍尔木兹海峡冲击 → 国际油价与波动率 → 中国宏观经济传导 → 政策缓冲与跨国反事实比较

## 题目拆解

1. 建立国际油价预测模型，解释 2026 年美伊冲突造成油价剧烈波动的机制和影响。
2. 以中国为例，刻画国际油价波动对经济增长的动态、非对称影响。
3. 比较主要石油进口国，解释中国应对此轮油价冲击的韧性并量化政策效果。

## 当前阶段：数据收集与审计

现在不指定最终主模型。以下内容仅是为了指导数据字段收集的候选方法方向，不代表最终选择：

| 子问题 | 候选方向 A | 候选方向 B | 选择前必须获得的证据 |
|---|---|---|---|
| Q1 | 含外生冲击的时间序列与波动模型 | 状态空间或非线性预测模型 | 平稳性、结构突变、波动聚集和滚动回测 |
| Q2 | 长短期及非对称传导模型 | 动态脉冲响应模型 | 共同样本、协整关系、滞后结构和稳定性 |
| Q3 | 跨国动态面板 | 中国政策反事实模型 | 对照国可比性、共同季度窗口和政策可观测性 |

模型族、滞后、预测步长、对照国和政策权重都要在 P0 数据审计后决定。仓库中不得写入未经真实代码产生的数值结论。

## 数据口径

- 当前数据冻结日：`2026-07-29`
- Q1 日度样本建议区间：`2010-01-01` 至 `2026-07-29`
- Q2 月度样本建议区间：`2010-01` 至最新完整月份；季度数据至 `2026Q2`
- Q3 跨国面板建议区间：`2010Q1` 至各国最新共同可得季度
- 战争反事实预测的训练截止日：`2026-02-27`

事件日期、变量定义和来源分别维护在：

- `data/metadata/event_timeline.csv`
- `data/metadata/data_dictionary.csv`
- `data/metadata/source_registry.csv`

P0 数据准入阈值维护在 `configs/data_audit.yaml`。项目级协作规则见根目录 `AGENTS.md`。

## 目录约定

```text
configs/        数据、事件与模型参数
data/raw/       原始下载文件，不直接提交大文件
data/interim/   中间清洗结果
data/processed/ 建模输入快照
data/metadata/  数据字典、来源与事件时间线
src/data/       数据采集、清洗和校验
src/q1_*/       第一问代码
src/q2_*/       第二问代码
src/q3_*/       第三问代码
results/        运行结果和复现清单
figures/        raw/process/result 三类图
support/        AI 工具使用说明等支撑材料
```

## 快速校验

元数据和 GitHub 固定快照可直接校验；EIA 原始 XLS/PDF/ZIP 审计需先安装 `requirements.txt` 并按 `data/raw/README.md` 放置哈希匹配的本地原文件：

```powershell
python -m src.data.validate_metadata
python -m src.data.audit_github_snapshot --check-only
python -m src.data.run_data_audit --check-only
python -m unittest discover -s tests -v
```

后续安装完整建模依赖：

```powershell
python -m pip install -r requirements.txt
```

## Git 约定

- `main`：稳定、可复现版本。
- 建议功能分支：`agent/data-pipeline`、`agent/q1-forecast`、`agent/q2-macro`、`agent/q3-policy`、`agent/paper`。
- 每个数据文件必须可追溯到来源登记；受许可限制或过大的原始文件仅记录 URL、获取时间和 SHA-256。
- `.env`、API 密钥、Office 临时文件、Python 缓存和 LaTeX 辅助文件不得提交。

## 当前状态

- [x] 题目文件归档
- [x] 仓库骨架与远程地址确定
- [x] 初版数据字典、来源登记、事件时间线
- [x] 数据优先阶段规则与审计准入标准
- [x] 队友 GitHub 日频数据首轮快照、官方逐值比对与结构审计
- [x] EIA 美国库存、全球供需和海湾停产量首轮快照与发布滞后审计
- [x] 记录霍尔木兹流量公开官方序列缺失及付费/代理备选路线
- [ ] 刷新存在发布滞后的 Brent、WTI、美元指数和 VIX 尾部观测
- [ ] P0 数据下载与字段核验
- [ ] P0 数据审计通过并冻结候选模型
- [ ] 建模手固定交付物与 M1 质检
- [ ] 编程手最小可运行结果与 P1/P2 质检
- [ ] 论文手双格式论文与 W1/W2 质检
