"""Демонстрация продукта целиком, одним прогоном.

Запуск:

    python scripts/demo.py                # весь сценарий подряд
    python scripts/demo.py --pause        # с остановкой перед каждым шагом
    python scripts/demo.py --seed 7       # другой эпизод

Семь шагов, в порядке, в котором их стоит показывать на записи: данные,
интерфейс агента, работа агента, оценка, проверка надёжности награды,
независимая проверка данных, базовые линии.

Интерфейса у продукта нет и быть не должно: это среда для дообучения модели,
её «пользователь» — агент, а не человек. Поэтому демонстрация терминальная, и
её задача — показать не картинки, а четыре вещи, которые проверяет задание:
контракт инструментов, доказуемость эталона, устойчивость награды к обману и
независимость проверки данных.

Скрипт ничего не записывает на диск и ничего не меняет в репозитории.
"""

from __future__ import annotations

import argparse
import json
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WIDTH = 78


def setup_console() -> None:
    """Включить UTF-8 на выводе: консоль Windows по умолчанию его не даёт."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


class Narrator:
    """Печать шагов с заголовками и необязательной остановкой."""

    def __init__(self, pause: bool) -> None:
        self.pause = pause
        self.step = 0

    def __call__(self, title: str, explanation: str = "") -> None:
        self.step += 1
        print()
        print("=" * WIDTH)
        print(f"  ШАГ {self.step}. {title}")
        print("=" * WIDTH)
        if explanation:
            print(explanation.strip())
            print()
        if self.pause:
            try:
                input("    [Enter — продолжить]")
            except EOFError:
                self.pause = False
            print()


def show(label: str, value) -> None:
    print(f"  {label:<34} {value}")


def demo(seed: int, pause: bool) -> int:
    from environment import MODE_CLOSED, make_env
    from evaluator import score
    from evaluator.oracle import build_oracle_submission
    from generator import build_episode
    from validator import verify_episode
    from validator.snapshot import public_snapshot, reachable_ids

    say = Narrator(pause)

    print()
    print("  RL-среда для дообучения моделей финансового аудита")
    print("  Команда: Лесхан Уаис, Тухватуллина Дилайла, Оспан Салих")
    print(f"  Эпизод построен по seed={seed}")

    # --- 1 -------------------------------------------------------------------
    say(
        "ДАННЫЕ: одна компания, один отчётный период",
        """
Генератор строит книги с нуля: счёта, платежи, проводки двойной записи и
ежедневные фиксинги курсов, а затем вносит дефекты четырёх типов. Суммы —
целые в минимальных единицах, курсы — десятичные строки: ни одного числа с
плавающей точкой в деньгах.
        """,
    )
    episode = build_episode(seed)
    manifest = episode["manifest"]
    show("компания", manifest.get("company_name", manifest["episode_id"]))
    show("период", f'{manifest["period_start"]} — {manifest["period_end"]}')
    show("базовая валюта", manifest["base_currency"])
    show("часовой пояс", manifest["timezone"])
    print()
    for table in ("ledger", "invoices", "payments", "fx", "policy"):
        show(f"записей в {table}", len(episode[table]))

    # --- 2 -------------------------------------------------------------------
    say(
        "ИНТЕРФЕЙС АГЕНТА: пять действий и ничего больше",
        """
Агент не получает книги целиком. Он запрашивает их через пять действий, и
каждый запрос стоит шаг. Наблюдение всегда имеет три поля: result, error,
remaining_steps. Ошибка приходит кодом из закрытого списка — ни путей, ни
seed, ни таймингов, через которые можно было бы угадать эталон.
        """,
    )
    env = make_env(MODE_CLOSED, time_limit_seconds=None)
    observation, _ = env.reset(seed, {})
    show("доступные таблицы", ", ".join(observation["tables"]))
    show("типы расхождений", ", ".join(observation["issue_types"]))
    show("бюджет шагов", observation["remaining_steps"])
    print()
    print("  запрос:  {\"name\": \"list_records\", \"args\": {\"table\": \"invoices\", \"limit\": 2}}")
    page, _, _, _, _ = env.step(
        {"name": "list_records", "args": {"table": "invoices", "limit": 2}}
    )
    first = page["result"]["records"][0]
    print("  ответ:   получено записей:", len(page["result"]["records"]))
    show("курсор следующей страницы", page["result"]["next_cursor"])
    show("первый счёт", f'{first["invoice_id"]}, {first["total_minor"]} {first["currency"]}')
    print()
    print("  запрос:  {\"name\": \"list_records\", \"args\": {\"table\": \"нет такой\"}}")
    bad, _, _, _, _ = env.step({"name": "list_records", "args": {"table": "нет такой"}})
    show("ответ", json.dumps(bad["error"], ensure_ascii=False))

    # --- 3 -------------------------------------------------------------------
    say(
        "АГЕНТ РАБОТАЕТ: базовая политика сверки",
        """
Политика reconcile ходит по таблицам, восстанавливает бухгалтерские тождества
и сдаёт выводы с доказательствами. Её задача — не высокий балл, а
доказательство, что каждый дефект выводится из публичных записей в пределах
бюджета шагов.
        """,
    )
    from runner.run_agent import load_policy, run as run_policy_in_protocol

    import tempfile

    from evaluator.episode_io import write_episode

    with tempfile.TemporaryDirectory() as directory:
        write_episode(episode, directory)
        outcome = run_policy_in_protocol(load_policy("reconcile"), directory, seed)

    submission = outcome["submission"]
    show("израсходовано шагов", outcome["inspection_steps"])
    show("сдано выводов", len(submission["findings"]))
    print()
    for finding in submission["findings"]:
        print(f'  • {finding["type"]}')
        show("  затронутые записи", ", ".join(sorted(finding["affected_ids"])))
        show("  заявленная сумма", f'{finding["claimed_amount_minor"]} {finding["currency"]}')
        show("  доказательств", len(finding["evidence_ids"]))

    # --- 4 -------------------------------------------------------------------
    available = frozenset(reachable_ids(public_snapshot(episode)))
    say(
        "ОЦЕНКА: взаимно однозначное сопоставление с эталоном",
        """
Вывод считается верным, только если совпали тип, затронутые записи, сумма с
объявленным допуском и валюта — и доказательства достаточны. Сопоставление
взаимно однозначное: ищется максимальное паросочетание, а не жадный проход,
иначе один вывод мог бы «закрыть» две ошибки эталона.
        """,
    )
    report = score(
        submission,
        episode["truth"],
        outcome["inspection_steps"],
        truncated=outcome["truncated"],
        available_evidence_ids=available,
    )
    show("ошибок в эталоне", len(episode["truth"]["issues"]))
    show("TP / FP / FN", f"{report.tp} / {report.fp} / {report.fn}")
    show("precision / recall / F1", f"{report.precision:.3f} / {report.recall:.3f} / {report.f1:.3f}")
    show("цена осмотра", f"-{0.002 * outcome['inspection_steps']:.3f}")
    show("ИТОГОВАЯ НАГРАДА", f"{report.reward:+.4f}")

    # --- 5 -------------------------------------------------------------------
    say(
        "НАДЁЖНОСТЬ НАГРАДЫ: обмануть оценщик нельзя",
        """
Главный вопрос к любому оценщику: что он даёт за правильный ответ без
обоснования. Берём эталонную заявку — все типы, записи и суммы верные — и
выбрасываем из неё доказательства. Затем возвращаем доказательства, но
подменяем одно выдуманным ID. Затем ломаем структуру заявки.
        """,
    )
    oracle = build_oracle_submission(episode["truth"])
    total = len(oracle["findings"])
    perfect = score(oracle, episode["truth"], 0, available_evidence_ids=available)
    show("эталонная заявка", f"TP={perfect.tp} FP={perfect.fp} FN={perfect.fn}, награда {perfect.reward:+.3f}")

    stripped = json.loads(json.dumps(oracle))
    for finding in stripped["findings"]:
        finding["evidence_ids"] = []
    naked = score(stripped, episode["truth"], 0, available_evidence_ids=available)
    show("без доказательств", f"TP={naked.tp} FP={naked.fp} FN={naked.fn}, награда {naked.reward:+.3f}")

    faked = json.loads(json.dumps(oracle))
    faked["findings"][0]["evidence_ids"].append("ID-КОТОРОГО-НЕТ")
    fabricated = score(faked, episode["truth"], 0, available_evidence_ids=available)
    show("с выдуманным ID", f"TP={fabricated.tp} FP={fabricated.fp} FN={fabricated.fn}, награда {fabricated.reward:+.3f}")

    broken = score({"episode_id": episode["truth"]["episode_id"], "findings": "не список"}, episode["truth"], 0)
    show("структура сломана", f"валидна={broken.valid}, награда {broken.reward:+.3f}")
    print()
    print(f"  Верных выводов было {total}. Без доказательств не зачтён ни один:")
    print("  правильный ответ без обоснования аудиторским выводом не является.")

    # --- 6 -------------------------------------------------------------------
    say(
        "НЕЗАВИСИМАЯ ПРОВЕРКА ДАННЫХ: эталон проверяется отдельным кодом",
        """
Валидатор получает только публичный снимок — доступа к эталону у него нет по
сигнатуре функции, а не по договорённости. Он держит бухгалтерские равенства,
заново выводит каждое расхождение, ищет расхождения, о которых эталон молчит,
и проверяет, что каждый объявленный ID доказательства действительно достижим
инструментом агента.
        """,
    )
    verdict = verify_episode(episode)
    show("эпизод корректен", verdict.ok)
    show("нарушений инвариантов", len(verdict.invariant_violations))
    show("расхождений восстановлено", len(verdict.reconstructed))
    show("незаявленных расхождений", len(verdict.undeclared_discrepancies))
    show("проблем с доказательствами", len(verdict.evidence_problems))
    show("награда эталонной заявки", f"{verdict.oracle_reward:+.3f}")
    disagreements = episode["provenance"]["derivation_disagreements"]
    show("расхождений с записью о внесении", len(disagreements))

    # --- 7 -------------------------------------------------------------------
    say(
        "БАЗОВЫЕ ЛИНИИ: награда различает стратегии",
        """
Четыре политики на этом эпизоде. Если формула награды устроена верно, они
обязаны разойтись: честная сверка выигрывает, «пометить всё» получает
минимум, случайный поиск тратит шаги зря.
        """,
    )
    from environment.engine import AuditEnv, run_policy
    from policies.mark_all_agent import MarkAllAgent
    from policies.random_agent import RandomExplorer
    from policies.reconciliation_agent import ReconciliationAgent

    print(f'  {"политика":<14}{"F1":>7}{"награда":>10}{"шагов":>8}{"TP":>5}{"FP":>5}{"FN":>5}')
    print("  " + "-" * 54)
    print(f'  {"oracle":<14}{perfect.f1:>7.3f}{perfect.reward:>+10.3f}{0:>8}{perfect.tp:>5}{perfect.fp:>5}{perfect.fn:>5}')
    for policy in (ReconciliationAgent(), RandomExplorer(), MarkAllAgent()):
        result = run_policy(AuditEnv(build_episode(seed)), policy)
        line = score(
            result["submission"],
            episode["truth"],
            result["inspection_steps"],
            truncated=result["truncated"],
            available_evidence_ids=available,
        )
        print(
            f'  {policy.name:<14}{line.f1:>7.3f}{line.reward:>+10.3f}'
            f'{result["inspection_steps"]:>8}{line.tp:>5}{line.fp:>5}{line.fn:>5}'
        )

    print()
    print("=" * WIDTH)
    print("  Дальше по желанию:")
    print("    python scripts/verify_all.py          обязательная проверка, шесть шагов")
    print("    python -m pytest tests -q             186 тестов, включая официальный набор")
    print("    python scripts/build_episode_sets.py  записать наборы train и dev")
    print("=" * WIDTH)
    print()
    return 0


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(description="Демонстрация продукта целиком.")
    parser.add_argument("--seed", type=int, default=3, help="эпизод для показа")
    parser.add_argument(
        "--pause", action="store_true", help="остановка перед каждым шагом"
    )
    arguments = parser.parse_args()
    return demo(arguments.seed, arguments.pause)


if __name__ == "__main__":
    raise SystemExit(main())
