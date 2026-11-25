import unittest

from . import harness
from .test_decision_gate import CODE


class FeatureScopeTests(unittest.TestCase):
    DEVICES = "汀洲采样仪（TZ-8）的封条印双鹤，海棠校验台（HT-2）的封条印三叶。三叶款要求使用新版默认初始化；双鹤款要求十组初始中心择优。"
    REPORTS = "采用鲸纹的是《北岸快讯》，采用蝶纹的是《南岭季刊》。蝶纹本按新版默认初始化，鲸纹本要求固定十次初始化。"
    PACKAGES = "「Orchid」（OC-7）发往 preview 渠道，「Fjord」（FJ-6）发往 stable 渠道。stable 构建采用新版默认初始化；preview 构建要求固定十次初始化。"

    def review(self, text, **kw):
        return harness.run(dict(filename="note.md", revision=2, current=text + CODE, **kw))

    def test_named_choices_and_signed_reply(self):
        for notes, kind, old, new in [
            (self.DEVICES, "artifact", "汀洲采样仪", "海棠校验台"),
            (self.REPORTS, "deliverable", "北岸快讯", "南岭季刊"),
            (self.PACKAGES, "artifact", "Orchid", "Fjord"),
        ]:
            text = notes + "本次归属待定。"
            result = self.review(text)
            self.assertEqual(result.get("decisionTarget"), kind)
            for side, name in (("old", old), ("default", new)):
                self.assertIn(name, result["questionChoices"][side])
                chain = result["choiceCitations"][side]
                self.assertGreaterEqual(len(chain), 2)
                self.assertTrue(all(c["quote"] in text.splitlines()[c["line"] - 1] for c in chain))
                self.assertTrue(any(name in c["quote"] for c in chain))
                answered = self.review(text, answer=side)
                self.assertEqual(bool(answered["proposed"]), side == "old")
                self.assertTrue(any(name in s["evidence"] for s in answered["trace"]))

    def test_current_assignment_by_feature_alias_or_name(self):
        for facts, assignment, changed in [
            (self.DEVICES, "本页封条上印的是双鹤。", True),
            (self.DEVICES, "本页随 HT-2 出货。", False),
            (self.REPORTS, "本次选定蝶纹本。", False),
            (self.PACKAGES, "本次部署的是 preview 构建。", True),
        ]:
            for text in (facts + assignment, assignment + facts):
                with self.subTest(assignment=assignment, text=text):
                    r = self.review(text)
                    self.assertEqual(r["status"], "complete")
                    self.assertEqual(bool(r["proposed"]), changed)

    def test_false_or_shared_marks_cannot_select_an_owner(self):
        for extra in ("隔壁设备封条印双鹤。", "如果本页封条上印的是双鹤再发送。", "本页可能是双鹤款。", "本页的挂扣两款通用。"):
            r = self.review(self.DEVICES + "本次归属待定。" + extra)
            self.assertEqual(r.get("decisionTarget"), "artifact")
            self.assertIsNone(r["proposed"])

    def test_reopened_assignment_in_same_sentence_keeps_both_choices(self):
        text = self.DEVICES + "本次选定双鹤款，但最终归属待定。"
        result = self.review(text)
        self.assertEqual(result["status"], "question")
        self.assertIsNone(result["proposed"])

    def test_a_shared_field_name_is_not_an_observed_identifier_value(self):
        notes = ("霜桥节点（Q7）的部署标签是 violet，龙潭节点（R9）的标签是 lime。"
                 "violet 要求十组初始中心择优，lime 要求使用新版默认初始化。")
        result = self.review(notes + "工单导出的部署标签是空值。")
        self.assertEqual(result.get("decisionTarget"), "artifact")
        self.assertIsNone(result["proposed"])

class DeviceOwnershipTests(unittest.TestCase):
    facts = ("送检清册列有岸边计量主机（潮汐盒）和巡线读取终端（飞鱼盒）。"
             "主机支持连接水尺接口，终端只读取离线卡片。"
             "水尺通道要求固定十次初始化，离线卡片通道采用新版默认初始化。")

    def inspect(self, text):
        from . import feature_scope
        return feature_scope.inspect(text) or {}

    def test_inventory_capability_and_policy_are_cited(self):
        report = self.inspect(self.facts + "本次随箱的是哪台尚待核实。")
        for key, name, feature in (("old", "岸边计量主机", "水尺"), ("default", "巡线读取终端", "离线卡片")):
            self.assertIn(name, report.get("questionChoices", {}).get(key, ""))
            chain = report["choiceCitations"][key]
            self.assertTrue(any(name in s["quote"] for s in chain))
            self.assertTrue(any(feature in s["quote"] and "初始化" not in s["quote"] for s in chain))

    def test_current_name_alias_or_observed_source_selects_device(self):
        for proof, side in (("本次装箱的是潮汐盒。", "old"), ("本页代码来自实际读取离线卡片的那台。", "default"),
                            ("本次选定岸边计量主机。", "old"),
                            ("这段代码是从读取离线卡片的设备导出的。", "default"),
                            ("签收单确认本次收到的设备带有水尺接口。", "old")):
            for text in (proof + self.facts, self.facts + proof):
                with self.subTest(proof=proof):
                    self.assertEqual(self.inspect(text).get("resolved"), side)

    def test_hypothetical_and_work_roles_are_not_assignment(self):
        for proof in ("假如本次装箱的是潮汐盒。", "本页可能取自飞鱼盒。", "本次没有选定潮汐盒。",
                      "本次潮汐盒负责收集水位，飞鱼盒负责记录。", "上次装箱的是潮汐盒。",
                      "若本次装箱的是潮汐盒就重测。", "本次未必来自飞鱼盒。", "本页取自未连接水尺的设备。",
                      "本次计划取自飞鱼盒，后因故取消。", "本次不选潮汐盒。", "本次并未选定潮汐盒。",
                      "本次取自水尺接口栏为空值的设备。", "本次随箱的是水尺接口字段未填写的设备。"):
            self.assertIsNone(self.inspect(self.facts + "交付设备尚未选定。" + proof).get("resolved"))

    def test_capability_is_valid_in_declaration(self):
        facts = ("海盐分析仪（盐盒）可以连接晶振模块，河谷读数站（谷盒）只能读取已保存的图片。"
                 "晶振模块按十次初始化，读数站按新版默认初始化。")
        self.assertEqual(self.inspect(facts + "本页示例来自实际使用晶振模块的设备。").get("resolved"), "old")

    def test_reverse_capability_declaration_matches_the_current_operation(self):
        text = ("能切换导轨的是仓储控制器，显示终端只读温度计。"
                "控制器每批固定十次初始化，显示终端采用新版默认初始化。"
                "这次要给现场实际切换导轨的一端更新操作说明。")
        self.assertEqual(self.inspect(text).get("resolved"), "old")
