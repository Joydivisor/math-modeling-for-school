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