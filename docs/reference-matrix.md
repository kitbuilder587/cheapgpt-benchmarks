# Матрица независимых сравнений

Перед официальным запуском комбинация модели, бенчмарка и reasoning effort должна присутствовать в [`references/matrix.yaml`](../references/matrix.yaml) со статусом `run`.

## Контракт первого релиза

Для всех четырёх моделей выбран GPQA Diamond в реализации Artificial Analysis Intelligence Index v4.1.1:

- 198 вопросов Diamond subset;
- 5 повторов каждого вопроса, всего 990 попыток на модель;
- reasoning effort совпадает с default CheapGPT для модели;
- temperature `0.6` согласно общему режиму Artificial Analysis;
- максимальный output cap `128000`, опубликованный OpenAI для GPT-5.5/5.6;
- открытый prompt и многоступенчатое regex-извлечение ответа;
- pass@1 считается по всем 990 попыткам.

| Модель | Effort | Независимый GPQA | Решение |
|---|---:|---:|---|
| `gpt-5.6-sol` | low | 89,798% | запускать |
| `gpt-5.6-terra` | medium | 87,172% | запускать |
| `gpt-5.6-luna` | medium | 85,859% | запускать |
| `gpt-5.5` | medium | 92,626% | запускать |

Матрица охватывает все 20 сочетаний четырёх V1-моделей и пяти бенчмарков на default effort:

| Benchmark | `sol` low | `terra` medium | `luna` medium | `gpt-5.5` medium |
|---|---|---|---|---|
| GPQA Diamond | run | run | run | run |
| HLE text-only | hold: judge | hold: judge | hold: judge | hold: judge |
| LiveBench | hold: только max | hold: только max | hold: только max | hold: только xhigh |
| MMLU-Pro | hold: нет reference | hold: нет reference | hold: нет reference | hold: нет reference |
| LiveCodeBench | hold: нет reference | hold: нет reference | hold: нет reference | hold: нет reference |

Точные URL, snapshot и причина решения для каждой ячейки находятся в machine-readable
[`references/matrix.yaml`](../references/matrix.yaml). `hold` означает запрет на официальный
расход токенов до появления сопоставимого reference или валидированного адаптера.

Первичный источник — [Artificial Analysis GPQA Diamond](https://artificialanalysis.ai/evaluations/gpqa-diamond), публичный фиксированный снимок — [Spring Prompt от 30 июля 2026](https://springprompt.com/benchmarks/gpqa-diamond), точная методика — [Artificial Analysis Intelligence Benchmarking](https://artificialanalysis.ai/methodology/intelligence-benchmarking).

Запуск выполняется командой:

```bash
CHEAPGPT_API_KEY=... uvx cheapgpt-benchmarks run \
  --model gpt-5.6-sol --profile full --track leaderboard --benchmark gpqa-diamond
```

## Почему не публикуются уже сделанные full-прогоны

Существующий GPQA-прогон `gpt-5.6-sol` содержит один ответ на вопрос и использует другой prompt. HLE оценён другим judge. LiveBench использует другой release, набор категорий и effort. Эти результаты полезны для диагностики runner, но не проходят правило сопоставимости и не должны служить публичным доказательством.

HLE остаётся исследованным вторым кандидатом: Artificial Analysis запускает 2 158 text-only вопросов один раз и оценивает их `gpt-5.6-luna` на medium. Новый HLE-run имеет смысл только после точного воспроизведения judge-контракта; до этого GPQA даёт более дешёвую и строгую проверку.
