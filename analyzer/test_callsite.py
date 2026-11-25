import ast
import unittest
from analyzer.callsite import locate, insertion
from analyzer.engine import PYTHON_BLOCK


class CallsiteTests(unittest.TestCase):
    def test_short_qualified_and_aliased_names(self):
        for imp, target in (("import sklearn.cluster", "sklearn.cluster.KMeans"),
                            ("import sklearn.cluster as c", "c.KMeans"),
                            ("from sklearn import cluster as c", "c.KMeans"),
                            ("from sklearn.cluster import KMeans as K", "K")):
            src = f"{imp}\ndef make(opts):\n    return {target}(**opts)"
            self.assertEqual(ast.unparse(locate(src).func), target)

    def test_ambiguous_or_shadowed(self):
        for stmt in ("def make(c):\n return c.KMeans()", "c.KMeans = substitute\nc.KMeans()",
                     "c.KMeans()\nc.KMeans()", "from plugin import *\nc.KMeans()",
                     "def c(): pass\nc.KMeans()", "c.KMeans(*params)"):
            with self.subTest(stmt=stmt), self.assertRaises(ValueError):
                locate("import sklearn.cluster as c\n" + stmt)

    def test_preserve_multiline_indentation_comments_and_unicode(self):
        note = ('正文\n```python\nfrom sklearn.cluster import KMeans\n'
                '模型 = KMeans(\n    4,  # 数目\n    random_state=1,\n)\n```\n')
        block = PYTHON_BLOCK.search(note)
        offset, addition = insertion(note, block, locate(block['code']))
        self.assertEqual(note[:offset] + addition + note[offset:],
                         note.replace("    random_state", "    n_init=10,\n    random_state"))
