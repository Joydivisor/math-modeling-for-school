# 原始数据目录

本目录中的实际下载文件默认由 `.gitignore` 排除。每次下载必须：

1. 使用 `source_registry.csv` 中登记的官方来源；
2. 保存原始文件，不在原文件上直接清洗；
3. 在下载日志中记录 UTC 获取时间、请求参数和来源版本；
4. 计算 SHA-256，并写入 `data/metadata/checksums.sha256`；
5. 将可公开且体量较小的建模输入写入 `data/processed/`；
6. 对受许可限制的数据只提交采集脚本、来源、字段说明和哈希。

## 当前 EIA 审计快照

将下列文件放入 `data/raw/eia/` 后运行 `python -m src.data.run_data_audit --check-only`：

| 本地文件 | 官方下载 | SHA-256 |
|---|---|---|
| `WCESTUS1w.xls` | `https://www.eia.gov/dnav/pet/hist_xls/WCESTUS1w.xls` | `52eb5f5464f417841f0070184263cc317338e88ef15823bda4088b7a98133805` |
| `STEO.zip` | `https://www.eia.gov/opendata/bulk/STEO.zip` | `a76fdf70a9106985b8235e3f4f20e48168f37233e421c67d0b39f3e3f532b454` |
| `jul26.pdf` | `https://www.eia.gov/outlooks/steo/archives/jul26.pdf` | `c1a0d6814be9ee54241b7eb650b26d3c1b1d1483f70f9b5021fd975b05f7d251` |

`WCESTUS1w.xls` 和 `STEO.zip` 会随官方发布更新。若当前官方字节与上述哈希不同，不得覆盖旧记录或修改哈希来“通过”检查；应新增带获取时间的新快照记录，并重新审计修订、尾部覆盖和历史/预测边界。
## NDRC 原始页面

2026 年 14 个调价窗口对应的 15 个官方 HTML 页面保存在本地 `data/raw/ndrc/`，不提交原始版权页面。逐页 URL 与 SHA-256 已写入 `data/metadata/ndrc_price_adjustments_2026.csv`。

## JODI 与 UN Comtrade 长历史

- JODI 2010—2025 年度文件放在 `data/raw/trade_energy/jodi_history/{primary|secondary}/`，2026 YTD 文件沿用 `data/raw/trade_energy/jodi_oil_{primary|secondary}_2026.csv`。34 个 URL、字节数、哈希和结构断言见 `configs/jodi_history_snapshot_20260730.json`。
- UN Comtrade 153 个正文放在 `data/raw/trade_energy/comtrade_hs2709_history/`，153 份最终 HTTP 响应头放在 `data/raw/trade_energy/comtrade_hs2709_headers/`。请求 URL、Comtrade reporter area code、M49 参考码、字节数和哈希见 `configs/comtrade_history_snapshot_20260730.json`。
- 原始 JODI CSV、Comtrade JSON/响应头均保持忽略；仓库只提交配置、哈希、审计代码和生成的元数据。重新获取后必须运行统一审计，不得仅替换配置哈希。

## E08 事件证据

四份页面放在 `data/raw/events/`；文件名、URL、哈希和机械标记见 `configs/event_e08_evidence_20260730.json`。其中 IEA 发布页只验证 `2026-07-10` 的报告发布日期，E08 发生窗口仍为 `2026-07-07` 至 `2026-07-08`。
