# 版本条款检索消融

同一份索引分别运行 BM25、向量、BM25 + 向量和默认的 BM25 + 向量 + Python AST。两种混合方式沿用线上倒数排名融合、通道阈值、并列排序和候选上限。单通道运行在排序函数中关闭其他通道，BM25 不执行向量推理。[排序代码](../../analyzer/library.py) · [运行脚本](../../scripts/retrieval_eval.py)

## 数据与相关性

27 篇笔记共切为 31 段。12 篇按路径引用仓库中已有笔记，其中 4 篇来自公开下游项目的中文摘编，另有 15 篇为本次编写的操作笔记。公开材料沿用原记录的来源和许可。[语料清单及原创正文](corpus.json) · [三个公开迁移样例的来源](../benchmark-public-migrations/sources.json) · [周期序列样例的来源](../benchmark-public-reference-final/sources.json)

11 个变更中，9 个各有一篇或多篇业务上值得核对的笔记，2 个没有相关笔记。每个变更列明旧、新条款、相关文件全集和理由，排序器只接收通过生产差分函数生成的条款。KMeans 缺省次数和 OneHotEncoder 参数更名取自仓库的版本场景；其余条款是对模拟系统的约定。涵盖英文条款匹配中文流程、别名调用、已有新写法、显式覆盖、外部配置、不相关同名词和同一 API 的无影响变更。此处“相关”包括需要确认外部配置或依赖方预期的笔记。稳定的显式值和只记旧环境的归档按无影响标记。[查询及逐条金标](queries.json)

这是开发期的小型诊断集。样本与相关性由同一编写者结合现有检索功能整理，未设独立标注或盲测。公开迁移笔记集中于同一个库；各条款等权，不能据此推算用户请求分布或模型在个人资料库的平均效果。

## 计分与实测

保留生产接口最多 30 个排序段落，按首次出现的文件名去重。Recall@5 是前 5 篇命中的金标文件数占该查询全部金标文件数的比例。MRR 是首个金标文件排名倒数的均值；候选中没有命中记 0。两项均只对 9 个非空查询取宏平均。空金标另计出现候选的查询数及它们前五名中的候选总数。

| 编码器 | 检索通道 | Recall@5 | MRR | 排序 P95（毫秒） | 空金标出现候选（共 2 个） |
|---|---|---:|---:|---:|---:|
| Concept hash | BM25 | 0.711 | 0.630 | 0.110 | 1 |
| Concept hash | 向量 | 0.656 | 0.537 | 0.479 | 0 |
| Concept hash | BM25 + 向量 | 0.767 | 0.667 | 0.474 | 1 |
| Concept hash | BM25 + 向量 + AST | 0.767 | 0.648 | 0.493 | 1 |
| MiniLM ONNX | BM25 | 0.711 | 0.630 | 0.184 | 1 |
| MiniLM ONNX | 向量 | 0.444 | 0.370 | 24.444 | 0 |
| MiniLM ONNX | BM25 + 向量 | 0.878 | 0.667 | 24.996 | 1 |
| MiniLM ONNX | BM25 + 向量 + AST | 0.878 | 0.667 | 22.847 | 1 |

两种混合检索都找到了旧关键字与解包配置，却把已经使用新写法的笔记排在第一。MiniLM 能找到仅用中文描述的楼层屏幕布局，默认概念向量遗漏该笔记；MiniLM 单独检索时，参数更名查询没有返回文档。两个编码器的三路融合都在“编码器 HTML 边框换色”时返回了 3 篇讲编码器调用的笔记，港口潮汐变更均无候选。AST 信号没有提高本集的 Recall@5，因此本轮保留原有默认排序。[概念向量逐案记录](concept.json) · [MiniLM 逐案记录](onnx.json)

计时对象为已建好索引的进程内单次 rank 调用，包含查询编码、通道计分、融合及命中说明。每查询 × 每通道先预热一次，随后按固定种子交错运行十轮，以 110 次实测的最近秩第 95 百分位计时；各轮对文档顺序做一致性校验。两个 BM25 行使用相同打分，没有调用模型。两组运行独立计时，绝对耗时受机器负载影响。建索引、输入反序列化、HTTP、Qdrant、首次加载模型均在该计时范围外。JSON 包含操作系统及架构、Python 和模型依赖版本、输入摘要、各笔记摘要、文档排名和每次耗时。

## 复现

在项目根目录运行。默认的概念向量无需额外模型。ONNX 使用下载脚本固定版本的权重及对应的 Python 环境；首次准备该环境可运行 `scripts/setup-library-model.sh`。有既有本地权重时可通过 `LIBRARY_MODEL_DIR` 指定目录。两次试验均使用本地向量后端。

```sh
unset LIBRARY_QDRANT_URL
LIBRARY_ENCODER=concept python3 scripts/retrieval_eval.py --output /tmp/retrieval-concept.json
LIBRARY_ENCODER=onnx .runtime/library-python/bin/python scripts/retrieval_eval.py --output /tmp/retrieval-onnx.json
python3 -m unittest scripts.test_retrieval_eval analyzer.test_library_ablation analyzer.test_library
```
