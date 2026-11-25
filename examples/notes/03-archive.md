# 旧版实验记录

历史记录：以下代码仅记录 scikit-learn 1.1.3 环境下的运行情况。

当时省略初始化次数，训练使用了 10 次初始化。

```python
from sklearn.cluster import KMeans

model = KMeans(n_clusters=3, random_state=17)
```
