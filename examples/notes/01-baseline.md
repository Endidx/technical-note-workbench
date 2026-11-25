# 聚类基线复现

为了和上一轮结果公平比较，升级后仍需保留 10 次初始化。

```python
from sklearn.cluster import KMeans

model = KMeans(n_clusters=8, random_state=42)
```
