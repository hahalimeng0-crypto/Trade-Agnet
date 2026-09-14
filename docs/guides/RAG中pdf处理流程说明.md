# RAG中pdf处理流程说明

## 1、功能目标

PDF 处理能力的目标是让用户可以直接上传 PDF 文件，并把其中可提取的文本转成 RAG 可处理的知识内容。在这个提交之前，上传内容更偏向纯文本；这个提交之后，系统可以识别 PDF、解析 PDF 字节、提取正文、切分成 chunk，并尝试进入混合检索索引。

## 2、实现能力

- 前端可以上传原始文件
- 有类似/api/upload支持真实文件上传，同时保留旧版JSON文本上传兼容
- 服务端可以识别`.pdf`文件和`application/pdf`类型
- PDF不按照普通UTF-8文本读取，而是走专门的PDF解析流程
- PDF文本提取优先级：
  - `pdfplumber`，
  - 2、`pdftotext`

- 解析出的文本会进行归一化，减少 PDF 排版噪声
- 文本会进入 RAG 的父子 chunk 切分流程
- 上传响应会返回解析器、页数、文本字符数、chunk 数、索引数、`doc_hash` 等信息
- 如果 PDF 可提取文本太少，会返回 `needs_ocr: true`，避免把扫描版 PDF 当作有效知识入库
- PostgreSQL 不可用时，会跳过实际索引和 embedding 调用，避免无效写入

# 3.PDF 解析策略

系统通过两个信号判断文件是否是 PDF：

- Content-Type 是 application/pdf
- 文件扩展名是 .pdf

解析优先级如下：

1. pdfplumber
   - 通过 Python 执行。
   - 会优先查找环境变量指定的 Python：
     - PDF_EXTRACT_PYTHON
     - PDF_PYTHON
   - 然后查找系统 python3。
   - 会输出类似 `--- page 1 ---` 的页标记。
2. pdftotext
   - 如果系统 PATH 中存在 pdftotext，会作为第二解析方案。
   - 使用 layout preservation 和 UTF-8 输出。
3. Go fallback
   - 使用 github.com/ledongthuc/pdf
   - 先尝试按行提取，再退回普通文本提取。

如果所有方案都无法提取有效文本，接口会返回需要 OCR 的错误或标记。

# 5. 文本归一化

PDF 提取出的文本通常带有换行、断词、空格和页眉页脚等噪声。当前归一化会处理：

- `\r\n` 和 `\r` 统一为 `\n`
- 移除空字节和软连字符。
- 修复英文断行连字符，例如 `RE-\nWARDS`
- 合并重复空格和 tab。
- 压缩过多空行。
- 去掉首尾空白。

这样可以减少无意义 chunk，提高后续检索质量。

# 6. RAG 切分方式

PDF文本进入RAG后使用small-to-big chunking：

```
完整文档文本
    |
    v
父chunk切分
    - size: max(rag.chunk_size * 4, 600)
    - overlap: rag.chunk_overlap * 2
    |
    v
子chunk切分
    - size: rag.chunk_size
    - overlap: rag.chunk_overlap
    |
    v
索引子chunk，并保留父chunk上下文
```

当前默认配置：

- rag.chunk_size = 200
- rag.chunk_overlap = 50
- 父chunk大小约800
- 父chunk overlap为100
- 子chunk大小为200
- 子chunk overlap为50

检索时先命中更精准的子chunk，再扩展到更大的父chunk给LLM使用。

# 7. 索引语义

当前混合索引顺序是：

1. 检查PostgreSQL是否可用。
2. 如果PostgreSQL不可用：
   - 返回已计算的doc_hash
   - 返回chunk数。
   - indexed_count = 0
   - 跳过embedding。
   - 跳过Milvus / Elasticsearch / Neo4j写入。
3. 如果PostgreSQL可用：
   - 生成embedding。
   - 保存chunk、parent content和embedding JSON到PG。
   - 可用时写入Milvus。
   - 可用时写入Elasticsearch。
   - 可用时异步触发Neo4j知识图谱索引。

Engine.Loaded 现在由实际成功索引数量决定。也就是说，PDF解析成功但索引失败时，不会误报RAG已加载。

# 8. 上传响应示例

成功上传并解析后，响应类似：

```
{
  "filename": "paper.pdf",
  "content_type": "application/pdf",
  "parser": "pdfplumber",
  "pages": 22,
  "text_chars": 76642,
  "needs_ocr": false,
  "chunk_count": 539,
  "parent_count": 102,
  "indexed_count": 0,
  "chunk_preview": [],
  "doc_hash": "sha256..."
}
```

如果 `needs_ocr = true`，说明该 PDF 可能是扫描版或图片型 PDF，当前不会进入 RAG。