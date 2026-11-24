# Evaluation · 2026-11-24

Golden set: `eval/golden.json`: 18 answerable + 5 unanswerable questions over the 10 synthetic documents. Answer model: `ollama:qwen3.5:4b`. Hardware: Apple M5, 16 GB.

## Retrieval

| Configuration | Hit@1 | Hit@3 | MRR | ms/query | Gate on unanswerable | Answerable wrongly refused |
|---|---|---|---|---|---|---|
| vector | 100% | 100% | 1.000 | 24 | – | – |
| keyword (BM25) | 94% | 100% | 0.972 | 0 | – | – |
| hybrid (RRF) | 100% | 100% | 1.000 | 37 | 4/5 refused | 0/18 |
| hybrid + rerank | 94% | 100% | 0.972 | 306 | 4/5 refused | 0/18 |

Gate calibration (top cosine similarity / top reranker logit per question):

- answerable: cosine 0.42–0.79, rerank 1.6–8.6
- unanswerable: cosine 0.28–0.65, rerank -11.2–6.8

## Answers (full pipeline)

- Answer accuracy (expected facts present / correct refusal): **100%**
- Citation accuracy (cites an expected file): **100%**
- Unverified rate (failed the number check): 0%
- Latency p50 2.1s · p95 4.2s

| id | pass | question | answer |
|---|---|---|---|
| q01 | ✅ | What was Nova Retail's revenue in Q1 2026? | Nova Retail's revenue in Q1 2026 was USD 1,250,000 [1]. |
| q02 | ✅ | What was Nova Retail's net income in Q2 2026? | Nova Retail Ltd reported a net income of **USD -155,000** for Q2 2026. This figure is derived from the operating loss of USD (149,000) and interest expense of U |
| q03 | ✅ | How much did Nova Retail spend on marketing in Q2 2026? | Nova Retail spent **USD 285,000** on marketing in Q2 2026. This figure is explicitly listed under Operating expenses (Marketing) in the Q2 2026 Income Statement |
| q04 | ✅ | What is Helix Foods' gross profit for Q2 2026? | Helix Foods' gross profit for Q2 2026 was SAR 1,210,000. This figure is reported directly on the income statement [1]. |
| q05 | ✅ | What were Nova Retail's total assets on June 30, 2026? | Nova Retail Ltd's total assets as of June 30, 2026 were USD 1,376,500 [1]. This figure is derived from the sum of current assets (USD 766,500) and property and  |
| q06 | ✅ | How much long-term debt does Nova Retail have? | Nova Retail Ltd has **USD 420,000** in long-term debt as of June 30, 2026. This figure is explicitly stated in the balance sheet [1] and confirmed by the verifi |
| q07 | ✅ | What is the total due on Atlas Logistics invoice INV-1042? | The total due on Atlas Logistics invoice INV-1042 is **USD 23,000.00** [4][5]. This amount includes freight services and warehousing charges for May 2026 plus a |
| q08 | ✅ | What VAT amount is on the Cedar Cloud invoice CC-311? | The VAT amount on the Cedar Cloud Services Ltd invoice CC-311 is **1,200.00**. [1] |
| q09 | ✅ | When was the wire transfer to Orion Consulting made and for how much? | The wire transfer to Orion Consulting was made on **2026-06-20** for an amount of **$25,000.00**. [1] |
| q10 | ✅ | How much rent did Nova pay to Harbor Properties in June? | Nova Retail Ltd paid **USD 30,000** for rent to Harbor Properties in June. This amount is confirmed by the bank statement showing a payment on June 24 [3] and m |
| q11 | ✅ | What is the closing balance of Nova Retail's June 2026 bank statement? | The closing balance of Nova Retail's June 2026 bank statement is **$226,500.00** [1]. This figure represents the final balance after all transactions recorded d |
| q12 | ✅ | What is the monthly fee cap in the logistics service agreement with Atlas? | The monthly fee cap in the logistics service agreement with Atlas Logistics LLC is **USD 25,000** per month [4]. |
| q13 | ✅ | How much notice is needed to stop the Atlas agreement from renewing? | To stop the Atlas agreement from renewing, **60 days** notice must be given [1]. The agreement runs for 24 months starting February 1, 2026, and renews automati |
| q14 | ✅ | Who wrote the Q2 2026 board memo? | Sara Malik wrote the Q2 2026 board memo [1]. |
| q15 | ✅ | Why did Nova Retail's revenue soften in Q2 2026? | Nova Retail's revenue softened in Q2 2026 because foot traffic declined in June. This information is stated in the Board Memo review of Q2 2026 [2]. |
| q16 | ✅ | Which customer deposited 56,300 in June? | Customer **Lumen Stores** deposited **56,300.00** on 2026-06-28 [1]. |
| q17 | ✅ | How did Nova Retail's revenue change from Q1 to Q2 2026? | Nova Retail's revenue decreased by **10.4%** from Q1 2026 to Q2 2026, dropping from USD 1,250,000 to USD 1,120,000 [1][2]. This decline was driven by a reductio |
| q18 | ✅ | Compare the gross margin of Nova Retail and Helix Foods in Q2 2026 | Nova Retail Ltd reported a gross margin of 42.0% in Q2 2026, while Helix Foods Company reported a lower gross margin of 35.6% for the same period [1][2]. Conseq |
| u01 | ✅ | What was Nova Retail's revenue in Q4 2025? | The uploaded documents do not contain the answer. Revenue for Nova Retail Ltd in Q4 2025 is not available; only data for Q1 2026 and Q2 2026 are provided [1][2] |
| u02 | ✅ | Who is the CEO of Tesla? | I couldn't find information about this in the uploaded documents. |
| u03 | ✅ | What is the weather forecast for Riyadh tomorrow? | I couldn't find information about this in the uploaded documents. |
| u04 | ✅ | How many employees does Google have? | I couldn't find information about this in the uploaded documents. |
| u05 | ✅ | What is the recipe for chocolate cake? | I couldn't find information about this in the uploaded documents. |
