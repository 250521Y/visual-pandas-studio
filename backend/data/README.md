# 示例数据来源

项目代码的 MIT 许可证不自动覆盖第三方数据。下列 CSV 用于演示和测试，不含应用用户上传的业务数据。

| 文件 | 来源与处理 | 许可 / 使用说明 |
| --- | --- | --- |
| `iris.csv` | 由 `scikit-learn.datasets.load_iris` 导出，重命名字段并附加 species；原始数据见 [UCI Iris](https://archive.ics.uci.edu/dataset/53/iris) | UCI 标注为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。署名：Fisher, R. (1936). Iris [Dataset]. UCI Machine Learning Repository. DOI: [10.24432/C56C76](https://doi.org/10.24432/C56C76)。 |
| `titanic.csv` | 取自 [mwaskom/seaborn-data](https://github.com/mwaskom/seaborn-data/blob/master/titanic.csv)，其来源说明指向 [Kaggle Titanic](https://www.kaggle.com/c/titanic/data) | 保留原始来源；seaborn-data 仓库未为所有数据声明统一许可。使用和再分发请核对原始来源的适用条款，不应将其视为本项目 MIT 授权的数据。 |
| `sales.csv` | 本项目 `backend/prepare_data.py` 用固定随机种子生成，包含用于清洗演示的缺失、重复与异常值 | 合成数据，随本项目按 MIT 许可证提供，不代表真实交易。 |

正常启动直接读取已提供的 CSV，不访问数据源。`prepare_data.py` 是可选维护工具；运行它还需要安装 `scikit-learn`。
