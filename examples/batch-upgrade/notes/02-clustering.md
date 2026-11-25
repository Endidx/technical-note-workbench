# 每周聚类复跑

为了和上一轮结果公平比较，升级后仍需保留 10 次初始化。

```python
from sklearn.cluster import KMeans
model = KMeans(n_clusters=6, random_state=7)
```
