# 发布后规则与模型辅助审阅留出集

这 15 篇中文笔记由 Codex 按人工设计题例的方式逐篇撰写，并逐篇预标动作、原因与原文证据。场景和代码均为此次新写的合成样例。设计者与标注者均为同一 AI 助手，未经过独立人类复核。设计时只检查了迁移资料和现有评测接口的输入、输出结构，未查看这些新样例的任何预测。

采用目的抽样。4 篇测试旧编码器参数更名，涵盖布尔值、运行时表达式和局部字典。3 篇具有明确的聚类迁移意图，3 篇缺乏明确意图，2 篇依赖外部配置或部署身份。另 3 篇代码在目标版本已满足需求。这里的类别有意覆盖不同决策，样本比例不能估计真实使用分布。

## 配对输入

两组使用同一份指令「帮我更新到目标版本」、同名同内容的笔记，以及 scikit-learn 1.1.3 到 1.4.2 的两份资料。每轮只传一篇笔记。只将笔记文件名、正文、版本资料和指令交给推理端。gold.json 的动作、分类、证据、原因、补丁均留在评分端。SHA256SUMS 包含所有正文、金标和本说明的哈希。

版本资料沿用待发布仓库 examples/batch-upgrade/sources 下的文件。sklearn-1.1.3.md 的 SHA-256 为 cad7ad4096085b3b4296ed8504d5ef6678b67a0e552a3a2b9a372fa96180b4c2，sklearn-1.4.2.md 的 SHA-256 为 9f59919eba697a3ff9b900802efcb6a80a3bc94a34efaefde1f2eed59a8aa80e。参数行为可对照 [KMeans 文档](https://scikit-learn.org/1.4/modules/generated/sklearn.cluster.KMeans.html) 和 [OneHotEncoder 迁移说明](https://scikit-learn.org/1.3/modules/generated/sklearn.preprocessing.OneHotEncoder.html)。

## 金标与评分映射

- 由 id 或 note 的无扩展名文件名关联结果。expected 的 edit 表示建议改，ask 表示补充证据或意图后再决定，keep 表示原样保留。三者均针对本篇代码和所给升级任务。所有样本均涉及目标 API，irrelevant 不能归并为 keep。
- 动作正确率以全部 15 篇为分母，另报匹配 edit、应追问的命中数、误建议修改数、阻塞和错误。无法返回结果仍计入总数，两个组使用相同分母。
- 6 篇应改笔记给出唯一的 old 和 replacement，可以构造参考全文。另报逐字匹配。对于 KMeans，只调整新增关键字的位置也可能正确，可单列 AST 等价结果。编码器改名须保留原表达式或原布尔值。ask、keep 的期望候选正文均为空。
- 追问的文字可以不同，reason 说明应澄清的具体缺口。evidence 是对应原文摘录，用于检查引用可定位；同义解释不能当作逐字引文。
- 既有 scripts/evaluate.py 的部分评分以及 Harness 提示专用于 KMeans。评估整套时需让两组都可见两项变更、均有表达三种动作的机会，并对改名使用对应的参考补丁。若只评估 KMeans，须预先按 family 筛选并注明 10 篇的分母，不能把 5 篇编码器结果算作 KMeans 结果。
