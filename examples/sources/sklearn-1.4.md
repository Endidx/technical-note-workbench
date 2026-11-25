# scikit-learn 1.4.2 · KMeans

> Changed in version 1.4: Default value for `n_init` changed to `'auto'`.

使用默认的 k-means++ 初始化时，auto 只运行 1 次。使用 random 或可调用初始化器时运行 10 次。仍支持显式传入整数。

[官方参数说明](https://scikit-learn.org/1.4/modules/generated/sklearn.cluster.KMeans.html)
