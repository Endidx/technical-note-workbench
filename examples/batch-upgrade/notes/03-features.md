# 分类特征转换

下游检查 NumPy 数组的形状，需要保持稠密输出。

```python
from sklearn.preprocessing import OneHotEncoder as OHE
encoder = OHE(sparse=False, handle_unknown="ignore")
```
