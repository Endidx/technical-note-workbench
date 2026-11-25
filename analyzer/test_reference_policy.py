import unittest

from analyzer.harness import run


def review(text, arguments='', **options):
    note = text + '\n\n```python\nfrom sklearn.cluster import KMeans\nmodel = KMeans(' + arguments + ')\n```\n'
    return run(dict(current=note, filename='experiment.md', revision=1, **options))


class ReferenceReviewTests(unittest.TestCase):
    def test_exact_source_and_effective_counts(self):
        text = '维护者要求当前调用与 scikit-learn 1.0.2 保持相同的初始化行为。'
        for args, changed, target in [('', True, 10), ("init='random'", False, 10)]:
            with self.subTest(args=args):
                result = review(text, args)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['proposed'] is not None, changed)
                evidence = result['referenceEvidence']
                self.assertIn('/1.0.2/', evidence['source'])
                self.assertEqual(evidence['targetCount'], target)

    def test_reference_missing_or_unverified(self):
        for target in ['升级前后', '与 1.0.9']:
            result = review('维护者要求当前调用' + target + '的初始化行为一致。', answer='old')
            self.assertEqual(result.get('questionType'), 'reference_evidence')
            self.assertIn('版本', result['question'])
            self.assertIsNone(result['proposed'])

    def test_match_only_named_implementation(self):
        text = 'EngineB 一侧执行 4 次初始化。EngineC 一侧执行 8 次初始化。维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        for args, change in [('n_init=2', True), ('', True), ('n_init=4', False)]:
            with self.subTest(args=args):
                result = review(text, args)
                self.assertEqual(result['status'], 'complete')
                self.assertEqual(result['proposed'] is not None, change)
                self.assertEqual(result['referenceEvidence']['targetCount'], 4)
                if change:
                    self.assertIn('n_init=4', result['proposed'])

    def test_missing_or_conflicting_peer_count(self):
        relation = '维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        for facts in ['EngineC 一侧执行 8 次初始化。', 'EngineB 一侧执行 4 次初始化。EngineB 一侧执行 6 次初始化。', 'EngineB 一侧最多执行 4 次初始化。']:
            with self.subTest(facts=facts):
                result = review(facts + relation, 'n_init=1')
                self.assertEqual(result.get('questionType'), 'reference_evidence')
                self.assertIn('EngineB', result['question'])
                self.assertIsNone(result['proposed'])

    def test_qualified_or_competing_current_policy(self):
        relation = '维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        for extra in ['维护者还要求当前调用必须使用 2 次初始化。', '但本次必须采用新版默认行为。']:
            result = review('EngineB 一侧执行 4 次初始化。' + relation + extra, 'n_init=1')
            self.assertEqual(result.get('questionType'), 'reference_evidence')
            self.assertIsNone(result['proposed'])

    def test_version_fact_on_another_line(self):
        text = '升级前使用 scikit-learn 1.0.2。\n维护者要求升级前后的初始化行为保持一致。\n评估环境为 scikit-learn 1.4.2。'
        result = review(text)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['referenceEvidence']['reference'], '1.0.2')
        self.assertEqual(len(result['referenceEvidence']['citations']), 2)

    def test_explicit_old_value_overrides_snapshot_default(self):
        text = '升级前使用 scikit-learn 1.0.2，显式设置 n_init=3。维护者要求升级前后的初始化行为保持一致。'
        result = review(text)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['referenceEvidence']['targetCount'], 3)

    def test_past_peer_observation_and_foreign_comparison_do_not_authorize_patch(self):
        text = 'EngineB 一侧执行 4 次初始化。其他项目要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        self.assertIsNone(review(text, 'n_init=1')['proposed'])

    def test_known_auto_on_current_side(self):
        text = 'EngineB 一侧执行 10 次初始化。维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        changed = review(text, "n_init='auto'")
        self.assertEqual(changed['status'], 'complete')
        self.assertIn('n_init=10', changed['proposed'])
        matched = review(text, "init='random', n_init='auto'")
        self.assertEqual(matched['referenceEvidence']['currentCount'], 10)
        self.assertIsNone(matched['proposed'])

    def test_reference_is_default_not_same_arguments(self):
        text = '维护者要求当前调用与 scikit-learn 1.0.2 默认的初始化次数保持一致。'
        for val in ["1", "'auto'"]:
            result = review(text, 'n_init=' + val)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['referenceEvidence']['targetCount'], 10)
            self.assertIn('n_init=10', result['proposed'])

    def test_dynamic_values_and_invalid_literal(self):
        text = 'EngineB 一侧执行 4 次初始化。维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        for args in ['n_init=budget', "init='callable'", "n_init='absent'", 'init=centers']:
            self.assertEqual(review(text, args).get('questionType'), 'reference_evidence')

    def test_explicit_current_is_not_historical_evidence(self):
        text = '维护者要求当前调用与 scikit-learn 1.0.2 保持相同的初始化行为。'
        result = review(text, 'n_init=3')
        self.assertEqual(result['questionType'], 'reference_evidence')
        self.assertIn('1.0.2', result['question'])

    def test_chinese_peer_name_and_negative_third_party_fact(self):
        text = '校验端以六次初始化拟合，辅助端以九次初始化拟合。维护者要求 scikit-learn 与校验端使用相同的初始化次数。'
        result = review(text, 'n_init=1')
        self.assertEqual(result['referenceEvidence']['targetCount'], 6)
        self.assertTrue(result['proposed'])
        negated = review(text.replace('校验端以六次初始化拟合', '校验端并非以六次初始化拟合'))
        self.assertEqual(negated['questionType'], 'reference_evidence')

    def test_edit_carries_applicability_audit(self):
        result = review('维护者要求当前调用与 scikit-learn 1.0.2 保持相同的初始化行为。')
        step = next(s for s in result['trace'] if s['tool'] == 'read_intent')
        self.assertEqual(step['applicability']['route'], 'reference')
        self.assertEqual(step['applicability']['outcome'], 'allow')
        self.assertEqual(step['applicability']['citations'], result['referenceEvidence']['citations'])

    def test_unknown_external_count_is_not_an_omitted_count(self):
        text = 'EngineB 一侧执行 10 次初始化。维护者要求 scikit-learn 与 EngineB 使用相同的初始化次数。'
        result = review(text, "init='random', **options", configFacts={'mapping':'options','init':'absent','n_init':'unknown'})
        self.assertEqual(result.get('questionType'), 'reference_evidence')
        self.assertIsNone(result['referenceEvidence']['currentCount'])

    def test_direct_maintainer_count(self):
        for text in ['维护者要求当前构造器改用十四次初始化。', '维护者决定把 n_init 明确指定为 14。']:
            for args in ['', 'n_init=8', 'n_init=14']:
                with self.subTest(text=text, args=args):
                    result = review(text, args)
                    self.assertEqual(result['status'], 'complete')
                    self.assertEqual(result['referenceEvidence']['targetCount'], 14)
                    self.assertEqual(result['proposed'] is not None, args != 'n_init=14')

    def test_direct_count_missing_or_conflicting(self):
        for text in ['维护者要求将此调用的 n_init 指定为正整数。',
                     '维护者要求当前调用使用 14 次初始化。维护者还要求当前调用使用 16 次初始化。']:
            result = review(text, 'n_init=2')
            self.assertEqual(result.get('questionType'), 'reference_evidence')
            self.assertIsNone(result['proposed'])

    def test_explicit_new_default_behavior(self):
        text = '维护者决定当前构造器的初始化次数采用新版默认行为。'
        for init, target in [("k-means++", 1), ("random", 10)]:
            result = review(text, f"init='{init}', n_init=4")
            self.assertEqual(result['referenceEvidence']['targetCount'], target)
            self.assertIn(f'n_init={target}', result['proposed'])

    def test_wrapper_uses_named_function_count(self):
        decision = '维护者要求该包装函数在未传参数时采用 calibrate 的默认初始化次数。'
        observation = 'calibrate 的 n_init 默认为 6。'
        result = review(decision + observation, 'n_init=3')
        self.assertEqual(result.get('status'), 'complete')
        self.assertEqual(result['referenceEvidence']['targetCount'], 6)
        self.assertEqual(len(result['referenceEvidence']['citations']), 2)
        for other in ['calibrate 的随机种子默认为 6。', 'other 的 n_init 默认为 6。']:
            self.assertEqual(review(decision + other, 'n_init=3').get('questionType'), 'reference_evidence')

    def test_current_direct_scope_exclusions(self):
        statements = ['维护者上次要求使用十四次初始化。', '如果用户选择甲，维护者要求使用十四次初始化。',
                      '维护者正在讨论是否将 n_init 指定为 14。', '维护者要求在十四次初始化和六次初始化之间二选一。',
                      '当前父版本的实现使用十四次初始化。', '维护者要求此处将随机种子设为 14，簇数为 6。',
                      '文档提到维护者要求其他项目使用十四次初始化。', '维护者要求当前调用使用 14 次初始化还是 6 次初始化？']
        for text in statements:
            with self.subTest(text=text):
                self.assertIsNone(review(text, 'n_init=3')['proposed'])

    def test_wrapper_default_with_separate_parameter_binding(self):
        decision = '维护者决定该包装函数未传参数时采用 calibrate 的默认值。'
        result = review(decision + '函数 calibrate 的 n_init 参数默认值为 5。')
        self.assertEqual(result.get('referenceEvidence', {}).get('targetCount'), 5)
        result = review(decision + '函数 calibrate 的随机种子默认值为 5。')
        self.assertIsNone(result['proposed'])

    def test_past_configuration_and_revoked_order(self):
        for text in ['当前父版本代码将 n_init 设为 14。', '当前函数使用的配置把 n_init 设为 14。',
                     '维护者要求当前调用使用 14 次初始化。该要求现已撤销。',
                     '维护者要求加速端使用 14 次初始化，此处展示 sklearn。']:
            with self.subTest(text=text):
                self.assertIsNone(review(text, 'n_init=3')['proposed'])

    def test_constructor_new_default_without_parameter_spelling(self):
        result = review('维护者决定当前 KMeans 调用采用新版默认。', 'n_init=7')
        self.assertEqual(result.get('referenceEvidence', {}).get('targetCount'), 1)

    def test_wrapper_default_from_unambiguous_signature(self):
        text = '维护者要求该包装函数无参时采用 calibrate 的默认初始化次数。'
        code = '\n\n```python\nfrom sklearn.cluster import KMeans\ndef calibrate(seed=3, n_init=7):\n    return None\nmodel=KMeans()\n```\n'
        result = run(dict(current=text + code, filename='test.md', revision=1))
        self.assertEqual(result.get('referenceEvidence', {}).get('targetCount'), 7)
        self.assertTrue(any(c['quote'].startswith('def calibrate') for c in result['referenceEvidence']['citations']))
        for variant in [code.replace('n_init=7', 'n_clusters=7'), code.replace('n_init=7', 'n_init=setting'),
                        code.replace('model=', 'calibrate = other\nmodel=')]:
            result = run(dict(current=text + variant, filename='test.md', revision=1))
            self.assertEqual(result.get('questionType'), 'reference_evidence')

    def test_ownership_choice_remains_available(self):
        text = '维护者要求当前调用固定十次初始化。教程组要求同一调用采用新版默认。两方共用同一段代码，尚未确定由谁作主。'
        result = review(text)
        self.assertEqual(result.get('decisionGap'), 'requirement_owner')

    def test_new_default_unknown_init(self):
        result = review('维护者决定当前 KMeans 调用采用新版默认。', 'init=make_centers, n_init=7')
        self.assertEqual(result.get('questionType'), 'reference_evidence')
        self.assertIn('init', result['question'])
        self.assertIsNone(result['proposed'])

    def test_signature_comment_or_duplicate_is_not_a_binding(self):
        text = '维护者要求该包装函数无参时采用 calibrate 的默认初始化次数。'
        for defs in ['# def calibrate(n_init=6): pass', 'def calibrate(n_init=4): pass\ndef calibrate(n_init=6): pass']:
            code = '\n\n```python\nfrom sklearn.cluster import KMeans\n' + defs + '\nmodel=KMeans()\n```\n'
            self.assertEqual(run(dict(current=text+code, filename='test.md', revision=0)).get('questionType'), 'reference_evidence')

    def test_requested_literal_auto_does_not_become_static_one(self):
        text = "维护者要求当前构造器显式指定 n_init='auto'。"
        result = review(text, "n_init=7")
        self.assertIsNone(result['proposed'])
        self.assertEqual(result.get('questionType'), 'reference_evidence')
        matched = review(text, "n_init='auto'")
        self.assertEqual(matched.get('status'), 'complete')
        self.assertIsNone(matched['proposed'])
