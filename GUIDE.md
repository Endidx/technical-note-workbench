# 使用与复验

## 运行

在 macOS、Linux 或 WSL 上准备 Python 3.9+ 和 JDK 17+，进入仓库根目录运行下面的命令。首次构建需要网络下载 Maven 与依赖。仓库附有 Maven Wrapper 和构建好的前端。

```sh
./run.sh
```

打开[本机资料库](http://127.0.0.1:8765/?view=library)。本地模式使用 H2，审阅状态和检查点签名密钥保存在 `data/`。按 Ctrl+C 停止，再次运行即可打开已保存的工作。

要使用 MySQL、RabbitMQ、MinIO、Qdrant 和通过 HTTP 调用的 Python 分析服务，先释放同一端口，再运行 `docker compose up --build`。浏览器仍访问 8765 端口，容器使用独立的持久卷。[部署配置](compose.yaml)

## 审阅五篇升级笔记

1. 在资料库选中五篇示例笔记和旧版资料，将资料名称填为 `scikit-learn`，版本填为 `1.1.3`，导入后再以同一名称导入 `1.4.2` 资料。[笔记](examples/batch-upgrade/notes) · [旧版资料](examples/batch-upgrade/sources/sklearn-1.1.3.md) · [新版资料](examples/batch-upgrade/sources/sklearn-1.4.2.md)
2. 等待索引发布，选择这两个版本，开始批量更新。在「分类特征转换」中，核对 API 的版本引文、原笔记行号，以及 `sparse=False` 改为 `sparse_output=False` 的差异。确认后点击「接受此修改」。
3. 「编码器实验配置」通过 `**encoder_options` 传入参数，缺少字典定义。在「补充依据」的草稿中，紧接构造调用前补入 `encoder_options = {"sparse": False}`，保存并重新调查。先核对新增的依据和键名修改，再决定是否接受。
4. 导出 ZIP。五篇笔记都有独立文件，已接受的笔记使用更新正文，待确认或待审批的笔记使用导入时的正文。批次绑定已发布的快照，之后继续导入也能复核本次使用的资料。

其他三篇各展示一种决策。每周聚类复跑要求保留旧初始化次数，提议增加 `n_init=10`。稀疏表笔记已使用新版参数，可以保留。样本量记录与当前迁移无关。

## 检索与导入

资料库支持 UTF-8 的 `.md` 和 `.markdown`。先用相同资料名分别导入两个版本，索引任务完成后选择「查找相关笔记」。展开结果可查看旧、新条款、命中段落和原文行号。排序融合 BM25、向量和 Python AST 标识符三个通道。批量调查会检查快照中的全部笔记。

本地默认编码器无需模型权重。可在 Python 3.10+ 环境运行下面的脚本，下载固定版本的量化多语言 MiniLM，校验摘要并建立独立运行环境。重启应用后，在已有资料库中点击「重建索引」，使笔记和查询使用相同编码器。[固定权重版本](https://huggingface.co/Xenova/paraphrase-multilingual-MiniLM-L12-v2/tree/2c4055b12046f11709e9df2c122e59ffbdc2f900)

```sh
./scripts/setup-library-model.sh
./run.sh
```

已准备本机权重时，Compose 可用以下命令挂载模型。[模型部署配置](compose.onnx.yaml)

```sh
docker compose -f compose.yaml -f compose.onnx.yaml up --build
```

## 调查使用的规划器

批次使用 Python 静态分析、意图规则和版本引文。单篇 KMeans 调查可在离线规则和模型工具调用间选择。默认规则在本机运行。模型规划器启用后，指定服务会收到当前笔记的证据和工具记录。可用以下环境变量配置服务，再重启应用。

| 变量 | 用途 |
| --- | --- |
| `HARNESS_PLANNER` | 设为 `remote`，允许模型选择下一个工具 |
| `HARNESS_BASE_URL` | 兼容 Chat Completions 的服务地址，通常以 `/v1` 结尾 |
| `HARNESS_MODEL` | 模型服务提供的名称 |
| `HARNESS_API_KEY` | 通过本机环境传入服务凭据 |
| `HARNESS_INTENT_BASE_URL`、`HARNESS_INTENT_MODEL`、`HARNESS_INTENT_API_KEY` | 单篇选择模型辅助意图判断时，配置负责语义判断的服务 |

单篇调查根据当前修订运行，每次工具完成后保存检查点。暂停后可以刷新或重启再继续。接受调查建议时，数据库在一笔事务中写入修订和回执，客户端重试可取回同一份回执。

## 复验

在仓库根目录运行。前四项可离线复算。下表中的 MiniLM 数字需要单独准备权重。

| 核验内容 | 命令与记录 |
| --- | --- |
| 配置是否只修改预期位置 | `python3 scripts/evaluate_batch_decisions.py --check`。[14 篇定向回归](examples/batch-decisions/README.md) |
| 公开提交的改名前后是否分别建议修改和保留 | `python3 scripts/replay_public_encoder.py`。[六个下游项目](examples/public-encoder/README.md) |
| 公开 KMeans 笔记是否能从意图推导出正确补丁 | `python3 scripts/evaluate.py --gold examples/benchmark-public-reference-final/gold.json --methods agent --agent-planner offline --output work/kmeans.json`。[八篇样本与标注方法](examples/benchmark-public-reference-final/README.md) |
| 检索召回是否因通道而异 | `LIBRARY_ENCODER=concept python3 scripts/retrieval_eval.py --output work/retrieval.json`。[语料、消融指标与 ONNX 复现命令](examples/retrieval-eval/README.md) |
| 并发与恢复边界 | 构建后端后运行配对实验，对比 1 路和 4 路，检查已提交的逐篇结果及恢复后的调用集合。[计时口径、原始记录与脚本](examples/batch-performance/README.md) |

在八篇 KMeans 样本上，离线单篇调查的首次动作正确 4/8。三篇需要修改的笔记全部漏改。f04 指出旧默认值为 10，调查却保留显式的 1。在 f03 中，新版默认已满足作者采用 `auto` 的决定，调查仍然追问。运行上表命令可查看每篇的期望动作、调查结果和引文。[输入](examples/benchmark-public-reference-final/notes) · [标注](examples/benchmark-public-reference-final/gold.json) · [调查输入与评分边界](examples/EVALUATION-DATA.md)

## 开发检查

```sh
python3 -m unittest discover -s analyzer -t .
python3 -m unittest discover -s scripts -p 'test_*.py'
./backend/mvnw -f backend/pom.xml package
(cd frontend && npm ci && npm test && npm run build)
python3 scripts/verify_batch.py
python3 scripts/verify_clarification.py
python3 scripts/verify_recovery.py
```

后三个脚本各自启动使用临时 H2 数据库的 JVM，分别检查批次导出、单篇补证和中断后的续跑及重复确认。第三项会主动终止它创建的测试进程。[批次检查](scripts/verify_batch.py) · [补证检查](scripts/verify_clarification.py) · [恢复检查](scripts/verify_recovery.py)
