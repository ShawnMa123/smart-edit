# L3 检索评测（20 题 · 任务 2.4 / 8.1 / 8.2）

- 服务：`http://59.110.213.187:8080`（检索走生产客户端 `HttpRetriever`，鉴权含在内）
- 语料：corpus.documents = 143
- 指标：**Recall@5 = 0.817** ｜ **MRR = 0.817**（文档级 gold）

| # | 问题 | gold 文档 | 检索到的文档（按序） | R@5 | 首位命中排名 |
|---|---|---|---|---|---|
| 1 | 进口货物的完税价格由哪些项目组成？ | cn-customs-law-2021, cn-customs-valuation-measures-2013 | cn-customs-law-2021, cn-customs-valuation-measures-2013 | 1.00 | 1 |
| 2 | 办理海关事务担保应当提交哪些材料？ | cn-customs-guarantee-2018 | cn-customs-guarantee-2018 | 1.00 | 1 |
| 3 | 被担保人要求变更担保内容的，应当如何办理？ | cn-customs-guarantee-2018 | cn-customs-guarantee-2018, jp-kanzei-hou-sekourei, cn-customs-law-2021 | 1.00 | 1 |
| 4 | 哪些情形下人民法院应认定当事人开立的独立保函？ | cn-independent-guarantee-2020 | cn-independent-guarantee-2020 | 1.00 | 1 |
| 5 | WTO反倾销协定下反倾销调查应如何发起？ | wto-adp | cn-anti-dumping-2004, wto-adp | 1.00 | 2 |
| 6 | 中国反倾销调查的立案条件和程序是什么？ | cn-anti-dumping-2004, cn-ad-cvd-1997 | cn-anti-dumping-2004 | 0.50 | 1 |
| 7 | CISG下卖方交付的货物不符合同，买方应在多长时间内通知？ | cisg | cisg | 1.00 | 1 |
| 8 | CISG对损害赔偿额如何计算？ | cisg | cisg | 1.00 | 1 |
| 9 | 美国海关对进口货物完税价格的估价方法有哪些？ | us-cfr-19-152 | cn-customs-valuation-measures-2013 | 0.00 | — |
| 10 | 美国商务部反倾销调查的程序规定是什么？ | us-cfr-19-165 | cn-anti-dumping-2004 | 0.00 | — |
| 11 | 日本关税定率法对关税估价是如何规定的？ | jp-kazei-teiritsu-hou | jp-kazei-teiritsu-hou | 1.00 | 1 |
| 12 | 澳大利亚出口管制法对受管制货物的许可要求是什么？ | au-export-control-act-2020 | cn-export-control-law-2020, au-export-control-act-2020 | 1.00 | 2 |
| 13 | 澳大利亚自治制裁如何指定受制裁的人和物？ | au-autonomous-sanctions-act-2011 | au-autonomous-sanctions-act-2011 | 1.00 | 1 |
| 14 | WTO贸易便利化协定对预裁定有什么要求？ | wto-tfa | wto-tfa, cn-customs-advance-ruling-2017, cn-customs-duty-collection-2024 | 1.00 | 1 |
| 15 | WTO保障措施的实施条件是什么？ | wto-safeg, cn-safeguard-2004 | cn-safeguard-2004, wto-safeg | 1.00 | 1 |
| 16 | WTO进口许可程序协定对许可的透明度有什么要求？ | wto-lic | wto-lic | 1.00 | 1 |
| 17 | 非优惠原产地规则下如何判定货物的原产国？ | cn-nonpreferential-origin-2018, cn-origin-2019, wto-ro | cn-nonpreferential-origin-2018, cn-customs-law-2021, cn-rcep-origin-2021 | 0.33 | 1 |
| 18 | 中国两用物项出口管制如何管理管制清单？ | cn-export-control-law-2020, cn-dual-use-export-control-2024 | cn-dual-use-export-control-2024 | 0.50 | 1 |
| 19 | 美国EAR出口管制有哪些许可例外？ | us-cfr-15-740 | us-cfr-15-740, us-cfr-15-730, us-cfr-15-732 | 1.00 | 1 |
| 20 | OFAC经济制裁的资产冻结（SDN名单）如何执行？ | us-cfr-31-501 | us-cfr-31-510, us-cfr-15-744, us-cfr-31-501, us-cfr-31-560 | 1.00 | 3 |

## 限制声明（任务 8.6）
- gold 为文档级标注（143 部法规下以「路由到正确法规」为度量单位），条文级 gold 仅在已核实条目上记录
- 未做 rerank 对照（服务端已开启 gte-rerank-v2，无法关闭对比）
- gold 标注由 AI 依据语料清单与已核实条文完成，**需人工复核**