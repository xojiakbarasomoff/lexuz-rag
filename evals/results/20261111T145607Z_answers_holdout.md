# Eval report — answers / holdout

- Date: 2026-11-11T14:50:16.332614+00:00
- Git commit: `801e957`
- Items: 20
- Embedding space: `fastembed:intfloat/multilingual-e5-large:1024`
- Retrieval config: {'top_k': 6, 'candidates': 40, 'rrf_k': 10, 'weights_semantic_lexical_articleref': [1.0, 0.25, 2.0], 'title_list': False, 'reranker': 'off', 'context_max_tokens': 6000}
- Prompt: `answer-v1` sha256 `c30ae786c78d3557`
- Benchmark manual verification: ai_drafted_unverified (no human review recorded yet)
- **Result status: PRELIMINARY - benchmark questions/references are not human-reviewed**
- Corpus:
  - istemolchilar-huquqlari: version `7c759eec74a0` (live_fetch, revision 02.02.2026, fetched 2026-11-11T05:01:53.614969+00:00)
  - mehnat-kodeksi: version `af3d92c6ade6` (local_import, revision 15.10.2026 01, fetched 2026-11-11T04:42:00+00:00)
- llm_model: gemini-3.5-flash-lite
- llm_provider: gemini
- llm_thinking_level: minimal
- sleep_between_items_s: 13.0
- checkpoint: evals\results\checkpoints\answers_holdout.jsonl
- resumed_rows: 0
- max_output_tokens: 2048
- prices_per_mtok_usd: [0.3, 2.5]
- llm_max_retries: 1
- cost_cap_usd: 1.0 (worst-case reservation per call, incl. repairs and retries)

## Results

| metric | value |
|---|---|
| samples | 20 |
| status_accuracy | 0.9 |
| answered_items_status_accuracy | 0.882 |
| refusal_clarification_accuracy | 1.0 |
| citation_precision_vs_expected | 0.9 |
| citation_recall_vs_expected | 0.824 |
| claim_citation_coverage | 1.0 |
| first_try_valid_rate | 0.95 |
| fallback_rate | 0.0 |
| provider_blocked | 0 |
| insufficient_evidence_returned | 3 |
| clarification_returned | 1 |
| errors | 1 |
| latency_ms_p50 | 4711 |
| latency_ms_p95 | 11455 |
| input_tokens | 80741 |
| output_tokens | 7537 |
| est_cost_usd | 0.0554 |
| not_run_due_to_cap | 0 |
| attempts_total | 20 |
| transient_provider_errors | 1 |
| all_attempts_llm_calls | 21 |
| all_attempts_tokens_in_out | [80741, 7537] |
| all_attempts_est_cost_usd | 0.0554 |
| model_versions_seen | ['gemini-3.5-flash-lite'] |
| validation_error_counts | {'quote not found verbatim': 1, 'no verifiable quote': 1} |
| budget_state | {'day': '2026-11-11', 'limit_usd': 1.0, 'spent_usd': 0.055416, 'reserved_usd': 0.0, 'expired_reservations': 0} |

Citation validity is enforced by the backend (invalid ids/quotes never reach the user); the rows below show how often the model needed a repair or fell back.

Semantic faithfulness is NOT measured here — see evals/RUBRIC.md (manual review pending).

## Status errors

- hold-08 (multi_article): expected answered, got insufficient_evidence 
- hold-10 (false_premise): expected answered, got error provider_unavailable

## Citations outside the expected articles (precision < 1)

### hold-03 (fact) - expected answered, got answered
- question: Qaysi xodimlarga dastlabki sinov belgilanmaydi?
- claim: Homilador ayollarga, uch yoshga to'lmagan bolasi bor ayollarga yoki uch yoshga to'lmagan bolani yolg'iz o'zi tarbiyalayotgan ota (vasiylarga) dastlabki sinov belgilanmaydi.
- claim: Zaxiraga qo'yiladigan ish o'rinlariga ishga joylashtirish uchun yuborilgan aholining ijtimoiy ehtiyojmand toifalaridan bo'lgan shaxslarga dastlabki sinov belgilanmaydi.
- claim: Davlat grantlari asosida o'qigan va oliy ta'lim tashkilotini tamomlagan kundan e'tiboran uch oy ichida yo'llanma bo'yicha olingan mutaxassisligiga doir ishga kirayotgan oliy ta'lim tashkilotlarining bitiruvchilariga dastlabki sinov belgilanmaydi.
- claim: Tegishli ta'lim tashkilotini tamomlagan kundan e'tiboran bir yil ichida birinchi bor ishga kirayotganda olingan mutaxassisligi bo'yicha mustaqil ravishda ishga joylashayotgan umumiy o'rta, o'rta maxsus, professional va oliy ta'lim tashkilotlarining bitiruvchilariga dastlabki sinov belgilanmaydi.
- claim: O'zi bilan olti oygacha muddatga mehnat shartnomasi tuzilayotgan xodimlarga dastlabki sinov belgilanmaydi.
- claim: O'n sakkiz yoshga to'lmagan shaxslarga dastlabki sinov belgilanmaydi.
- claim: Ishga qaytadan qabul qilingan taqdirda ish beruvchi ilgari qaysi xodimlar bilan mehnat shartnomasini alohida asoslar bo'yicha bekor qilgan bo'lsa, o'sha shaxslarga dastlabki sinov belgilanmaydi.
- claim: Ishlab chiqarishda o'qitish shartnomasi bo'yicha ushbu ish beruvchida o'qishni o'tagan o'quvchilarga dastlabki sinov belgilanmaydi.
- claim: Jamoa kelishuvlarida, shuningdek jamoa shartnomasida va ish beruvchining ichki hujjatlarida nazarda tutilgan boshqa xodimlarga ham dastlabki sinov belgilanmaydi.
- claim: Vaqtinchalik xodimlarni ishga qabul qilish chog'ida ham dastlabki sinov belgilanmaydi.
- cited S1 = mehnat-kodeksi:129
- cited S4 = mehnat-kodeksi:496
- expected articles: ['mehnat-kodeksi:129']

### hold-05 (fact) - expected answered, got answered
- question: To'liqsiz ish vaqtida ishlaganda ish haqi qanday to'lanadi?
- claim: Toʻliqsiz ish vaqti shartlarida ishlaydigan xodimlarning mehnatiga haq toʻlash ular ishlab bergan vaqtiga mutanosib ravishda yoki haqiqatda ishlab chiqargan mahsulotiga qarab amalga oshiriladi.
- cited S1 = mehnat-kodeksi:258
- cited S2 = mehnat-kodeksi:186
- expected articles: ['mehnat-kodeksi:186']

### hold-06 (script_variant) - expected answered, got answered
- question: Йиллик меҳнат таътили неча кун?
- claim: Har yilgi asosiy eng kam mehnat taʼtilining davomiyligi yigirma bir kalendar kunni tashkil etadi.
- claim: I va II guruh nogironligi boʻlgan xodimlarga davomiyligi kamida oʻttiz kalendar kundan iborat yillik mehnat taʼtili beriladi.
- limitation: Ayrim toifadagi xodimlar va qoʻshimcha taʼtillar haqidagi boshqa qoidalar ushbu manbalarda toʻliq keltirilmagan.
- cited S1 = mehnat-kodeksi:217
- cited S3 = mehnat-kodeksi:429
- expected articles: ['mehnat-kodeksi:217']


## Expected article not cited (recall < 1, answered)

### hold-16 (paraphrase) - expected answered, got answered
- question: Telefonimning nuqsoni kafolat muddatida chiqdi, do'kon tuzatib berishi shartmi?
- claim: Tovarda kafolat muddatida topilgan nuqsonlarni sotuvchi isteʼmolchi tegishli talab qoʻygan paytdan eʼtiboran yigirma kun ichida bepul bartaraf etishi lozim.
- cited S2 = istemolchilar-huquqlari:15
- expected articles: ['istemolchilar-huquqlari:13']


## Needed a repair call (first output failed validation)

### hold-01 (fact) - expected answered, got answered
- question: Besh kunlik ish haftasida necha dam olish kuni beriladi?
- claim: Besh kunlik ish haftasida xodimlarga haftada ikki dam olish kuni beriladi.
- cited S1 = mehnat-kodeksi:207
- expected articles: ['mehnat-kodeksi:207']
- validation error: claim 1: quote not found verbatim in S1: 'Besh kunlik ish haftasida xodimlarga haftada ikki dam olish kuni beriladi'
- validation error: claim 1: no verifiable quote


## Provider safety blocks (not the same as missing evidence)

- none

## Status errors - full detail

### hold-08 (multi_article) - expected answered, got insufficient_evidence
- question: Ortiqcha ishlaganim uchun pul o'rniga dam olish vaqti olsam bo'ladimi, bunda qanday to'lanadi?
- limitation: Taqdim etilgan manbalarda ortiqcha ishlangan vaqt uchun pul o'rniga dam olish vaqti berilishi va uning qanday to'lanishi haqida yetarli ma'lumot mavjud emas.
- expected articles: ['mehnat-kodeksi:262']

### hold-10 (false_premise) - expected answered, got error (error provider_unavailable)
- question: Homiladorligi sababli ayolni ishga olishni rad etish mumkin-ku?
- expected articles: ['mehnat-kodeksi:392']


## Transient provider errors (all attempts, kept even when retried)

- hold-10 at 2026-11-11T14:53:07.417097+00:00: provider_unavailable (8561 ms)

## Not run (cost cap)

- none
