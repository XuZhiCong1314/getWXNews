# WeChat Article Links Scraper

批量抓取微信公众号文章链接，并可选调用 AI 生成中文总结。

## 功能

- 批量抓取多个公众号文章链接
- 使用 `wechat_accounts.json` 维护共享 `cookie`、`token`、`fingerprint` 和多个 `fakeid`
- 支持日期过滤
- 不传日期时默认使用当天日期
- 默认输出到 `./output`
- 可选抓取文章正文并调用 AI 输出中文总结
- AI 总结同时输出 `JSON` 和 `Markdown`

## 文件

- [wechat_article_links_scraper.py](/F:/Temple/getwxNews/wechat_article_links_scraper.py)
- [wechat_accounts.json](/F:/Temple/getwxNews/wechat_accounts.json)
- [ai_config.json](/F:/Temple/getwxNews/ai_config.json)

## 依赖

```bash
pip install requests
```

## 公众号配置

编辑 [wechat_accounts.json](/F:/Temple/getwxNews/wechat_accounts.json)：

```json
{
  "cookie": "在这里填写 mp.weixin.qq.com 的完整 Cookie",
  "token": "在这里填写 mp.weixin.qq.com 的 token 参数",
  "fingerprint": "在这里填写 appmsgpublish 请求中的 fingerprint 参数",
  "accounts": [
    {
      "name": "account_1",
      "fakeid": "MzkzMjgxOTEyOQ=="
    },
    {
      "name": "account_2",
      "fakeid": "MjM5OTE2MzUwNA=="
    }
  ]
}
```

说明：

- `cookie`：微信公众平台后台请求头里的完整 Cookie，所有公众号共用
- `token`：微信公众平台后台请求参数里的 token，通常同一登录会话共用
- `fingerprint`：`appmsgpublish` 请求中的指纹参数，建议保留
- `accounts`：要抓取的公众号列表
- `name`：自定义名称，用于输出区分
- `fakeid`：目标公众号的 fakeid

## 如何获取 `cookie` / `token` / `fakeid`

下面这套方法来自这篇 Bilibili 专栏：

- 文章链接：[如何使用python脚本爬取微信公众号文章？](https://www.bilibili.com/read/cv31427597/)

按文章里的思路，获取步骤如下：

1. 登录微信公众平台 `mp.weixin.qq.com`
2. 新建一篇图文消息
3. 在编辑器里点击“超链接”
4. 选择“选择其他公号”
5. 搜索并选中你要抓取的目标公众号
6. 按 `F12` 打开浏览器开发者工具
7. 进入 `Network`
8. 筛选 `Fetch/XHR`
9. 在公众号选择弹窗里翻页，找到最新的 `appmsgpublish` 请求

在这个请求里取值：

- `cookie`
  在请求头 `Request Headers` 里，找到 `cookie:` 整行，复制完整值

- `token`
  在请求的 Query String Parameters 或 Payload 里找到 `token`

- `fakeid`
  在请求的 Query String Parameters 或 Payload 里找到 `fakeid`
  如果为空，说明你抓到的还不是目标公众号对应请求，需要重新在“选择其他公号”页翻页后抓一次

- `fingerprint`
  在请求参数里找到 `fingerprint`

把这些值填进 [wechat_accounts.json](/F:/Temple/getwxNews/wechat_accounts.json) 即可。

## AI 配置

支持在一个文件里同时保存 OpenAI 和 Qwen：

```json
{
  "provider": "openai",
  "openai": {
    "api_key": "你的OpenAI密钥",
    "model": "gpt-4.1-mini"
  },
  "qwen": {
    "api_key": "你的Qwen密钥",
    "model": "qwen-plus"
  }
}
```

## 基本运行

默认按当天日期抓取，输出到 `./output`：

```bash
python wechat_article_links_scraper.py
```

默认每个公众号最多请求 `5` 次列表接口，避免翻页过久。

指定日期范围：

```bash
python wechat_article_links_scraper.py --start-date 2025-01-01 --end-date 2025-03-31
```

指定输出目录：

```bash
python wechat_article_links_scraper.py --output-dir ./my_output
```

指定请求上限：

```bash
python wechat_article_links_scraper.py --max-requests-per-account 2
```

取消请求上限：

```bash
python wechat_article_links_scraper.py --max-requests-per-account 0
```

## AI 总结

按 [ai_config.json](/F:/Temple/getwxNews/ai_config.json) 里的默认 `provider` 执行：

```bash
python wechat_article_links_scraper.py --summarize
```

强制使用 Qwen：

```bash
python wechat_article_links_scraper.py --summarize --summary-provider qwen
```

强制使用 OpenAI：

```bash
python wechat_article_links_scraper.py --summarize --summary-provider openai
```

自定义 Markdown 输出文件名：

```bash
python wechat_article_links_scraper.py --summarize --summary-markdown my_summary.md
```

## 输出文件

默认保存在 `./output`：

- `wechat_articles.csv`
- `wechat_articles.json`
- `wechat_raw_response.json`
- `wechat_ai_summary.json`，启用 `--summarize` 时生成
- `wechat_ai_summary.md`，启用 `--summarize` 时生成

如果配置了多个公众号，原始响应文件会按账号分别保存。

## 注意事项

- `cookie`、`token`、API Key 都是敏感信息，不要提交到公开仓库
- `fingerprint` 建议保留；有时不填也能用，但稳定性较差
- 如果当天没有匹配文章，启用 `--summarize` 时会自动跳过总结
