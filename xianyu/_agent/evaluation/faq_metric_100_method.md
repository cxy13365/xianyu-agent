# 100 条 FAQ 基础集说明

`faq_metric_100_cases.json` 是扩展评测集的 FAQ 基础部分，覆盖发货时效、快递、退货政策、商品成色和新旧程度，每类 20 条。

仅用这 100 条 FAQ 测试可以评估常见问题回答和知识库检索，不能有效评估转人工率、转人工准确率、实时订单问题或高风险问题。完整的 170 条测试集、指标口径和最新结果见 [`faq_metric_170_method.md`](faq_metric_170_method.md)。

基础集离线检索回归命令：

```powershell
& .\services\xianyu-worker\.venv\Scripts\python.exe .\evaluation\build_faq_metric_100_cases.py
& .\services\xianyu-worker\.venv\Scripts\python.exe .\evaluation\evaluate_faq_metric_100.py
```

基础集在线流水线脚本保留在 `evaluate_faq_metric_100_live.py`；最新完整线上测试应使用 `evaluate_faq_metric_170_live.py`，避免只测到 FAQ 场景。
