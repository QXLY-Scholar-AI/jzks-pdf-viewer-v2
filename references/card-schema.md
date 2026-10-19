# reading.json

UTF-8 JSON，物理页码从1开始。五个steps的id分别为1到5。

```json
{
  "schema": "jzks-pdf-viewer/v1",
  "paper": {"title": "论文标题", "authors": "作者", "doi": "可为空"},
  "summary": "整篇论文的连贯概括",
  "steps": [{
    "id": 1, "title": "作者想解决什么问题",
    "paragraphs": [{"title": "具体问题", "text": "精读正文", "layer": "author", "refs": ["E01"]}]
  }],
  "annotations": [{
    "id": "E01", "step": 1, "page": 1,
    "title": "批注标题", "kind": "method", "quote": "从原文复制的实际短引句",
    "explanation": "中文解释", "layer": "author"
  }]
}
```

一个引句应尽量在同一页且能唯一定位。用原文中的词句而非中文翻译或生成的概括。`layer`仅取`author`或`analysis`，引用ID必须存在。

`kind`为`background`、`method`、`result`、`question`或`implication`，表示批注用途，与作者/AI来源标签独立。发现结果冲突也可标为question。旧记录未提供kind时按所属步骤补默认值。

五部分正文还应包含研究地图、可检验问题、作者声称的缺口、方法适配、直接证据结论与作者主张对照，以及有机制和区分检验的替代解释。先记录`evidence-conclusions.md`，说明是否已接触作者结论及实际材料范围，再写最终JSON。

网页展示的原页由PDF直接渲染，坐标由实际引句匹配产生。若唯一匹配失败，脚本保留未定位状态；禁止仅为通过定位而填写与解读无关的引句。
