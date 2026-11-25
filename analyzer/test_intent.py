"""Handwritten unit tests for scope/negation; independent of benchmark files."""
import unittest

from analyzer.intent import infer


class IntentTests(unittest.TestCase):
    def test_count_must_modify_initializations_not_clusters_or_seed(self):
        for sample in (
            "验收要求每个模型从十组不同的初始中心出发。",
            "迁移时请把每次拟合的初始化次数固定为 10。",
            "为保持可比性，必须沿用旧版的初始化次数。",
            "After upgrading, we must keep ten independent initializations.",
        ):
            with self.subTest(sample=sample):
                found = infer(sample)
                self.assertEqual(found.intent, "old")
                self.assertIn(found.evidence, sample)
        for sample in (
            "下次将样本分成十个簇，可以探索更多初始化策略。",
            "为了稳定，请把 random_state 固定为 10。",
            "过去每轮试了十组不同的初始中心。",
            "为便于比较，需要保留二十次初始化。",
            "知道旧版会做十次初始化，暂时不要求保持该行为。",
        ):
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent, "unknown")

    def test_new_default_is_an_affirmative_choice(self):
        for sample in (
            "目的是观察 1.4 的默认策略，直接按库的缺省行为运行。",
            "这个示例请跟随升级后的默认配置。",
            "We want to use the new defaults.",
            "不用保留十次初始化，直接采用新版默认设置。",
        ):
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent, "default")
        self.assertEqual(infer("这里不要保留十次初始化。").intent,"unknown")
        self.assertEqual(infer("新版默认改为一次初始化。").intent,"unknown")

    def test_conflicts_and_questions(self):
        samples = (
            "需要十次初始化；另一个验收条件是采用新版默认。",
            "要不要保留 10 次初始化？",
            "还没决定采用新版默认，还是沿用旧版的初始化次数。",
            "要求保留十次初始化。禁止保留十次初始化。",
        )
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent,"unknown")

    def test_scope_of_history_and_pins(self):
        self.assertEqual(infer("该项目的运行环境仍锁在 scikit-learn 1.1.3。").intent,"pinned")
        self.assertEqual(infer("以下仅用于归档，记录了 scikit-learn 1.1.3 的聚类实验。").intent,"history")
        self.assertEqual(infer("旧资料曾建议锁定 scikit-learn 1.1.3。").intent,"unknown")
        self.assertEqual(infer("别的项目锁定 scikit-learn 1.1.3。本项目采用新版默认。").intent,"default")
        self.assertEqual(infer("为了对照，其他服务仍需做十次初始化。").intent,"unknown")

    def test_quoted_and_fenced_examples_cannot_set_scope(self):
        sample = "> 本项目锁定 scikit-learn==1.1.3\n\n```text\n必须保留十次初始化。\n```\n\n本例直接使用新版默认。"
        out = infer(sample)
        self.assertEqual(out.intent,"default")
        self.assertIn(out.evidence, sample)

    def test_resolving_question_does_not_reinterpret_a_version_pin(self):
        self.assertEqual(infer("本项目锁定 scikit-learn==1.1.3", "old").intent, "pinned")
        self.assertEqual(infer("留下草稿待讨论。", "old").intent, "old")

    def test_a_cluster_count_a_bound_or_a_conditional_is_not_a_target(self):
        for sample in (
            "这里要求十个初始中心。",
            "每次拟合最多十次初始化。",
            "为了控制算力，要求最多十次初始化。",
            "如果需要保留十次初始化，就在配置里明确指定。",
            "请检查是否仍需要十次初始化。",
            "旧版默认执行十次初始化。此前大家必须遵守这个约定。",
            "要求先查清楚升级后的默认配置。",
        ):
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent, "unknown")

    def test_explicit_trials_of_center_initialization(self):
        self.assertEqual(infer("每次调用都必须为起始中心做十次试验。").intent, "old")

    def test_fit_budget_resolved_across_clauses(self):
        for sample in (
            "每个周期先准备十套候选质心，再取目标函数值最低的一套。",
            "这条记录约定的是一次拟合的起点预算：独立跑 10 遍，以惯量最小者作为交付结果。",
            "旧环境会比较 10 组起始点。迁移后这条初始化预算保持不变。",
            "起始中心的试验预算是硬约束，每次请求固定十组。",
            "迁移验收必须与旧版本省略 n_init 时的行为一致。",
            "每个样本窗口必须维持旧版本的默认初始化行为。",
        ):
            with self.subTest(sample=sample):
                result = infer(sample)
                self.assertEqual(result.intent,"old")
                self.assertIn(result.evidence, sample)

    def test_unrelated_count_or_upper_bound_does_not_bind_to_starts(self):
        for sample in (
            "一次拟合使用不同起点择优。另做 10 遍计时再报告平均耗时。",
            "预算有限，总共训练 10 个模型，各模型都挑最优解。",
            "每次聚类选十个质心，随后检查起点的质量。",
            "每批需要生成若干候选初始中心，记录了十次网络调用。",
            "当前预算最多运行十组起点。升级后继续沿用这个上限。",
            "旧系统会试十组随机起点，然后选最好的结果。",
            "历史报告列出十组起始点。下一次只要求画图保持旧风格。",
        ):
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent, "unknown")

    def test_unresolved_choice_outweighs_default_in_different_sentence(self):
        for sample in (
            "对照实验遵循新版默认。基线复现需要不同的起点预算。当前还没决定选哪一种用途。",
            "示范用的是新版默认，但是否追求与旧默认一致还需确认。",
        ):
            with self.subTest(sample=sample):
                self.assertEqual(infer(sample).intent, "unknown")
        self.assertEqual(infer("采用新版的默认设置。图例颜色仍未确定。").intent, "default")
