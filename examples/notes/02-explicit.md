# 用户分群流水线

每周重跑一次客户分群，固定参数以便比较不同批次。

```python
from sklearn.cluster import KMeans

model = KMeans(n_clusters=5, n_init=10, random_state=7)
```
