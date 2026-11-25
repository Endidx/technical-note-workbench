# scikit-learn 1.4.2 · KMeans

> Changed in version 1.4: Default value for `n_init` changed to `'auto'`.

使用默认的 k-means++ 初始化时，auto 只运行 1 次。使用 random 或可调用初始化器时运行 10 次。仍支持显式传入整数。

[官方参数说明](https://scikit-learn.org/1.4/modules/generated/sklearn.cluster.KMeans.html)

## OneHotEncoder

OneHotEncoder 的 sparse 参数在 1.2 更名为 sparse_output，旧参数在 1.4 移除。将关键字改为 sparse_output，保留原值。

[OneHotEncoder 官方参数说明](https://scikit-learn.org/1.4/modules/generated/sklearn.preprocessing.OneHotEncoder.html)

[1.2 迁移公告](https://scikit-learn.org/1.4/whats_new/v1.2.html#sklearn-preprocessing)
