import unittest

from . import harness
from .test_decision_gate import CODE


class ObjectScopeTests(unittest.TestCase):
    def review(self, body, **kwargs):
        return harness.run(dict(filename="note.md", revision=2, current=body + CODE, **kwargs))

    def test_undecided_delivery_names_both_objects_and_cites_their_actual_rules(self):
        for first, second in (("岑溪标定箱", "河湾展架"), ("河湾展架", "岑溪标定箱")):
            body = f"“{first}”（Delta）在新版固定十次初始化；“{second}”（Sigma）在新版使用默认初始化。说明卡随实物发货，工位上放的是哪件还没核实。"
            result = self.review(body)
            self.assertEqual(result.get("decisionTarget"), "artifact")
            for side, name, policy in (("old", first, "固定十次初始化"), ("default", second, "使用默认初始化")):
                self.assertIn(name, result["question"])
                self.assertIn(policy, result["questionChoices"][side])
                for quote in result["choiceCitations"][side]:
                    self.assertIn(quote["quote"], body)
                self.assertIn(policy, result["choiceEvidence"][side]["quote"])
                self.assertEqual(bool(self.review(body, answer=side)["proposed"]), side == "old")

    def test_selected_device_uses_only_its_version_and_requirement(self):
        cards = "“岩台记录仪”仍用 1.1.3；“谷口终端”已升至 1.4，必须保留十次初始化。"
        for device, edit in [("岩台记录仪", False), ("谷口终端", True)]:
            for text in (cards + f"这张操作卡随{device}发货。", f"这张操作卡随{device}发货。" + cards):
                result = self.review(text)
                self.assertEqual(result["status"], "complete")
                self.assertEqual(bool(result["proposed"]), edit)
                trace = next(s for s in result["trace"] if s["tool"] == "read_intent")
                self.assertIn(device, trace["evidence"])
        current = "已确认这张操作卡仍给断网的 1.1.3 记录仪。隔壁的终端才升级到 1.4。"
        self.assertEqual(self.review(current)["status"], "complete")
        self.assertIsNone(self.review(current)["proposed"])

    def test_unsettled_or_foreign_device_assignment_cannot_authorize_a_patch(self):
        cards = "“岩台记录仪”仍用 1.1.3；“谷口终端”已升至 1.4，必须保留十次初始化。"
        for statement in ("这张卡随哪台设备尚未确定。", "另一份说明随谷口终端发货，本页随哪台设备尚未确定。"):
            result = self.review(cards + statement)
            self.assertEqual(result["status"], "question")
            self.assertIsNone(result["proposed"])

    def test_the_current_card_names_version_and_policy_together(self):
        for policy, edit in (("要求固定十次初始化", True), ("直接使用新版默认初始化", False)):
            text = f"这张操作卡给运行 1.4 的记录仪，{policy}。另一台终端仍用 1.1.3。"
            result = self.review(text, intentMode="model")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(bool(result["proposed"]), edit)

    def test_selection_via_printed_alias_does_not_confuse_a_different_card(self):
        rules = "“西丘样机”（Cedar）使用新版默认初始化；“河湾展架”（Birch）在新版固定十次初始化。"
        for who, edit in [("Cedar", False), ("Birch", True)]:
            result = self.review(rules + f"本页随{who}发货。")
            self.assertEqual(result["status"], "complete")
            self.assertEqual(bool(result["proposed"]), edit)
        result = self.review(rules + "本页随哪件实物还没核实。另一份文档写的是Birch。")
        self.assertEqual(result.get("decisionTarget"), "artifact")

    def test_pinned_recipient_reply_preserves_its_environment_in_conclusion(self):
        text = "“岩台记录仪”仍用 1.1.3；“谷口终端”已升至 1.4，必须保留十次初始化。这张卡随哪台设备尚未确定。"
        result = self.review(text, answer="default")
        self.assertIsNone(result["proposed"])
        self.assertIn("1.1.3", result["reason"])

    def test_neighbouring_devices_requirement_cannot_spill_into_current_sheet(self):
        text = "这张操作卡给运行 1.4 的记录仪，另一个终端要求固定十次初始化。"
        self.assertIsNone(self.review(text)["proposed"])

    def test_single_legacy_recipient_needs_no_second_machine(self):
        result = self.review("这张操作卡仍给没有联网的 1.1.3 放映机。")
        self.assertEqual(result["status"], "complete")
        self.assertIsNone(result["proposed"])

    def test_stored_legacy_data_does_not_identify_current_runtime(self):
        from . import object_scope
        self.assertIsNone(object_scope.inspect("本页用于存有 1.1.3 样本的工作站。"))

    def test_unverified_physical_ownership_cannot_use_a_single_known_policy(self):
        text = "“西丘样机”要求固定十次初始化；“溪桥样机”每次运行十次抽样。这份说明随实物出厂，仍不知道工位是哪台设备。"
        result = self.review(text)
        self.assertIn(result["status"], ("question", "blocked"))
        self.assertIsNone(result["proposed"])

    def test_pending_unlabelled_crate_cannot_inherit_only_visible_policy(self):
        text = "质检那边要求固定十次初始化。使用卡随实物发货，工位放的是哪只箱还没核实。"
        self.assertIsNone(self.review(text)["proposed"])

    def test_packing_list_requires_both_named_options_until_plate_is_read(self):
        text = ("只有拆开背板才能读铭牌。备料单列着杏湾演示匣（XW-D），说明卡应保留 1.4.2 的默认初始化；"
                "也列着乌桕比对匣（WJ-R），说明卡应在 1.4.2 固定十次初始化。库管还没有拆板，手上的卡要配给架上那只。")
        result = self.review(text)
        self.assertEqual(result.get("decisionTarget"), "artifact")
        for side, name in (("default","杏湾演示匣"), ("old","乌桕比对匣")):
            self.assertIn(name, result["questionChoices"][side])
            self.assertIn(name, result["question"])
            self.assertIn(result["choiceEvidence"][side]["quote"],text)

    def test_local_seal_confirms_which_environment_to_preserve(self):
        text = ("库房把两套设备的卡片一并送来。网络台装 1.4.2；这页右上角的铅封号已经和离线柜对上，"
                "柜内一直用 1.1.3。请保留当年省略次数的例子供旧柜操作员照抄。")
        from . import object_scope
        result = object_scope.inspect(text)
        self.assertEqual((result or {}).get("resolved"), "pinned")
        self.assertIn("铅封号", result["citation"].quote)
        self.assertIsNone(self.review(text)["proposed"])

    def test_work_order_names_recipient_after_and_before_device_policies(self):
        rules = "晨桥仪（CQ-9）在新版固定十次初始化；石门仪（SM-1）应使用新版默认初始化。"
        proof = "本页按随货工单分配。查到工单登记的是 CQ-9。"
        for text in [rules + proof, proof + rules]:
            from . import object_scope
            self.assertEqual((object_scope.inspect(text) or {}).get("resolved"), "old")
            self.assertTrue(self.review(text)["proposed"])
        for detail in ("工单还未查到。", "上次工单登记的是 CQ-9。", "另一台的工单登记的是 CQ-9。", "工单并未登记为 CQ-9。"):
            result = self.review(rules + "本页按随货工单分配。" + detail)
            self.assertEqual(result.get("decisionTarget"), "artifact")
            self.assertIsNone(result["proposed"])

    def test_location_proof_and_separate_policy_keep_exact_evidence(self):
        text = ("“西仓展台”（XA）在北仓；该设备要求固定十次初始化。"
                "“东仓展台”（XB）在南仓；该设备要求使用新版默认初始化。"
                "本页按安装位置选设备。查到本页的安装位置是南仓。")
        from . import object_scope
        self.assertEqual((object_scope.inspect(text) or {}).get("resolved"), "default")

    def test_inventory_lookup_carries_sheet_reading_table_and_policy_sources(self):
        text = ("“南岸验收仪”（N-A）要求新版固定十次初始化；“北岸样机”（N-B）采用新版默认初始化。"
                "本页按库存号配发。已查到库存号 K39。库存对照表中 K39 对应 N-A，K93 对应 N-B。")
        from . import object_scope
        report = object_scope.inspect(text)
        self.assertEqual(report.get("resolved"), "old")
        evidence = " ".join(c["quote"] for c in report["citations"])
        for fragment in ("按库存号配发","已查到库存号 K39","K39 对应 N-A","固定十次初始化"):
            self.assertIn(fragment,evidence)
        unavailable = text.replace("已查到库存号 K39", "库存号尚未查到")
        self.assertEqual(object_scope.inspect(unavailable).get("decisionTarget"),"artifact")

    def test_unperformed_identification_step_keeps_the_prerequisite_in_evidence(self):
        from . import object_scope
        rules = "“西丘样机”在新版固定十次初始化；“河湾展架”使用新版默认初始化。"
        for prerequisite, missing in (
            ("只有拆开背板才能读铭牌。", "库管还没有拆板，手上的卡要配给架上那只。"),
            ("打开防护盖才能辨认资产编号。", "现场尚未开盖，本页按资产编号分配。"),
            ("需要扫描标签才能辨认库存号。", "现场还没扫描，本页按库存号分配。"),
        ):
            info = object_scope.inspect(prerequisite + rules + missing)
            self.assertEqual(info.get("decisionTarget"), "artifact")
            evidence = [c["quote"] for c in info["citations"]]
            self.assertIn(prerequisite, evidence)
            self.assertIn(missing, evidence)
