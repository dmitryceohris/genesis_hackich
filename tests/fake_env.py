"""Тестовый двойник среды над фикстурами.

Это НЕ ``environment/``. Настоящую среду пишет её владелец; здесь ровно столько
поведения, сколько нужно, чтобы базовые политики и тесты оценщика работали, пока
среды нет:

- пять действий из раздела 04 задания;
- страница не больше 50 строк, стабильные курсоры;
- неизвестный ID или действие даёт ограниченную ошибку и расходует шаг;
- максимум 100 шагов, ``submit`` завершает эпизод;
- в наблюдениях нет ни эталона, ни seed, ни путей, ни таймингов.

Когда появится настоящая среда, тесты политик переключаются на неё заменой
конструктора: протокол действий тот же.
"""

from __future__ import annotations

from decimal import Decimal, DecimalException, getcontext
from typing import Any

from evaluator.contract import MAX_STEPS

PUBLIC_TABLES = ("ledger", "invoices", "payments", "fx", "policy")

MAX_PAGE_LIMIT = 50

#: Ключ публичного ID для каждой таблицы.
TABLE_ID_FIELD = {
    "ledger": "row_id",
    "invoices": "invoice_id",
    "payments": "payment_id",
    "fx": "fx_id",
    "policy": "policy_id",
}

# Ограниченные коды ошибок. Один код на класс ситуации, без деталей:
# иначе текст ошибки становится каналом утечки.
ERR_UNKNOWN_ACTION = "unknown_action"
ERR_UNKNOWN_TABLE = "unknown_table"
ERR_NOT_FOUND = "not_found"
ERR_INVALID_CURSOR = "invalid_cursor"
ERR_INVALID_LIMIT = "invalid_limit"
ERR_INVALID_EXPRESSION = "invalid_expression"
ERR_INVALID_ARGUMENTS = "invalid_arguments"
ERR_EPISODE_FINISHED = "episode_finished"


class _ExpressionError(Exception):
    pass


def evaluate_expression(expression: str, *, max_length: int = 256, max_depth: int = 16) -> Decimal:
    """Арифметика на Decimal: + - * / и скобки, никакого кода.

    Реализация рекурсивного спуска. Допускаются только десятичные литералы,
    унарные знаки и четыре операции. Имена, вызовы, степени и побитовые
    операции не разбираются вовсе, а не фильтруются после разбора.
    """
    if type(expression) is not str or not expression or len(expression) > max_length:
        raise _ExpressionError("bad expression")

    getcontext().prec = 34
    position = 0

    def peek() -> str | None:
        nonlocal position
        while position < len(expression) and expression[position] == " ":
            position += 1
        if position >= len(expression):
            return None
        return expression[position]

    def parse_expression(depth: int) -> Decimal:
        if depth > max_depth:
            raise _ExpressionError("too deep")
        value = parse_term(depth)
        while True:
            char = peek()
            if char == "+":
                advance()
                value += parse_term(depth)
            elif char == "-":
                advance()
                value -= parse_term(depth)
            else:
                return value

    def parse_term(depth: int) -> Decimal:
        value = parse_factor(depth)
        while True:
            char = peek()
            if char == "*":
                advance()
                value *= parse_factor(depth)
            elif char == "/":
                advance()
                divisor = parse_factor(depth)
                if divisor == 0:
                    raise _ExpressionError("division by zero")
                value /= divisor
            else:
                return value

    def parse_factor(depth: int) -> Decimal:
        char = peek()
        if char == "+":
            advance()
            return parse_factor(depth)
        if char == "-":
            advance()
            return -parse_factor(depth)
        if char == "(":
            advance()
            value = parse_expression(depth + 1)
            if peek() != ")":
                raise _ExpressionError("unbalanced parenthesis")
            advance()
            return value
        return parse_number()

    def parse_number() -> Decimal:
        nonlocal position
        peek()
        start = position
        seen_dot = False
        while position < len(expression):
            char = expression[position]
            if char.isdigit():
                position += 1
            elif char == "." and not seen_dot:
                seen_dot = True
                position += 1
            else:
                break
        if start == position:
            raise _ExpressionError("number expected")
        literal = expression[start:position]
        if literal == ".":
            raise _ExpressionError("number expected")
        try:
            return Decimal(literal)
        except DecimalException as error:  # pragma: no cover - защитная ветка
            raise _ExpressionError("bad literal") from error

    def advance() -> None:
        nonlocal position
        position += 1

    result = parse_expression(0)
    if peek() is not None:
        raise _ExpressionError("trailing input")
    return result


class FakeEnv:
    """Минимальная среда над одним эпизодом-фикстурой."""

    def __init__(self, episode: dict, *, max_steps: int = MAX_STEPS) -> None:
        self._episode = episode
        self._max_steps = max_steps
        self._steps_used = 0
        self._inspection_steps = 0
        self._finished = False
        self._submission: Any = None
        self._truncated = False

    # --- свойства для доверенной стороны -------------------------------------
    # Эти значения читает оркестратор и оценщик, а не агент.

    @property
    def inspection_steps(self) -> int:
        return self._inspection_steps

    @property
    def truncated(self) -> bool:
        return self._truncated

    @property
    def submission(self) -> Any:
        return self._submission

    @property
    def truth(self) -> dict:
        """Эталон. Доступен только доверенной стороне, не агенту."""
        return self._episode["truth"]

    # --- интерфейс среды ------------------------------------------------------

    def reset(self) -> tuple[dict, dict]:
        self._steps_used = 0
        self._inspection_steps = 0
        self._finished = False
        self._submission = None
        self._truncated = False
        observation = {
            "task": (
                "Найдите расхождения в книгах компании за отчётный период и "
                "подтвердите каждое доступными записями."
            ),
            "manifest": dict(self._episode["manifest"]),
            "policy": dict(self._episode["policy"][0]),
            "tables": list(PUBLIC_TABLES),
            "issue_types": list(
                ("duplicate_invoice", "payment_allocation", "fx_conversion", "period_cutoff")
            ),
            "remaining_steps": self._max_steps,
        }
        return observation, {}

    def step(self, action: object) -> tuple[dict, float, bool, bool, dict]:
        if self._finished:
            # Повторный step после завершения не начисляет и не меняет журнал.
            return {"error": ERR_EPISODE_FINISHED, "remaining_steps": 0}, 0.0, True, False, {}

        self._steps_used += 1
        remaining = self._max_steps - self._steps_used

        if type(action) is not dict:
            return self._inspection_result({"error": ERR_UNKNOWN_ACTION}, remaining)

        name = action.get("name")

        if name == "submit":
            self._finished = True
            self._submission = action.get("findings")
            return (
                {"result": "submitted", "remaining_steps": remaining},
                0.0,
                True,
                False,
                {},
            )

        result = self._dispatch(name, action)

        # Если исследовательское действие стало сотым, эпизод усекается и
        # оценивается пустая заявка.
        if remaining <= 0:
            self._finished = True
            self._truncated = True
            self._submission = None
            self._inspection_steps += 1
            return {**result, "remaining_steps": 0}, 0.0, False, True, {}

        return self._inspection_result(result, remaining)

    def _inspection_result(self, result: dict, remaining: int) -> tuple[dict, float, bool, bool, dict]:
        self._inspection_steps += 1
        # Награда за исследование нулевая в любом режиме.
        return {**result, "remaining_steps": remaining}, 0.0, False, False, {}

    def _dispatch(self, name: object, action: dict) -> dict:
        if name == "list_records":
            return self._list_records(action)
        if name == "get_record":
            return self._get_record(action)
        if name == "get_document":
            return self._get_document(action)
        if name == "calculator":
            return self._calculator(action)
        return {"error": ERR_UNKNOWN_ACTION}

    def _list_records(self, action: dict) -> dict:
        table = action.get("table")
        if table not in PUBLIC_TABLES:
            return {"error": ERR_UNKNOWN_TABLE}

        limit = action.get("limit", MAX_PAGE_LIMIT)
        if type(limit) is not int or type(limit) is bool or not 1 <= limit <= MAX_PAGE_LIMIT:
            return {"error": ERR_INVALID_LIMIT}

        cursor = action.get("cursor")
        rows = self._episode[table]
        if cursor is None:
            offset = 0
        elif type(cursor) is str and cursor.isdigit() and int(cursor) <= len(rows):
            offset = int(cursor)
        else:
            return {"error": ERR_INVALID_CURSOR}

        page = rows[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = str(next_offset) if next_offset < len(rows) else None
        return {
            "result": {
                "table": table,
                "rows": [dict(row) for row in page],
                "next_cursor": next_cursor,
            }
        }

    def _get_record(self, action: dict) -> dict:
        table = action.get("table")
        if table not in PUBLIC_TABLES:
            return {"error": ERR_UNKNOWN_TABLE}
        record_id = action.get("id")
        if type(record_id) is not str:
            return {"error": ERR_INVALID_ARGUMENTS}
        field = TABLE_ID_FIELD[table]
        for row in self._episode[table]:
            if row.get(field) == record_id:
                return {"result": dict(row)}
        # Один и тот же код для неизвестного и для скрытого ID.
        return {"error": ERR_NOT_FOUND}

    def _get_document(self, action: dict) -> dict:
        doc_id = action.get("doc_id")
        if type(doc_id) is not str:
            return {"error": ERR_INVALID_ARGUMENTS}
        for kind in ("invoices", "payments"):
            for document in self._episode[kind]:
                if document.get("doc_id") == doc_id:
                    return {"result": _deep_copy(document)}
        return {"error": ERR_NOT_FOUND}

    def _calculator(self, action: dict) -> dict:
        expression = action.get("expression")
        try:
            value = evaluate_expression(expression)
        except (_ExpressionError, DecimalException):
            return {"error": ERR_INVALID_EXPRESSION}
        return {"result": {"value": str(value)}}


def _deep_copy(value):
    if isinstance(value, dict):
        return {key: _deep_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_deep_copy(item) for item in value]
    return value


def run_policy(env: FakeEnv, policy) -> dict:
    """Прогнать политику до завершения эпизода.

    Возвращает журнал переходов в формате траекторий. Эталона в наблюдениях нет:
    среда его не выдаёт, а эта функция ничего не добавляет.
    """
    observation, _ = env.reset()
    generator = policy.run(observation)
    trajectory: list[dict] = []

    try:
        action = next(generator)
    except StopIteration:
        action = {"name": "submit", "findings": {"episode_id": env.truth["episode_id"], "findings": []}}

    step_index = 0
    while True:
        step_index += 1
        observation, reward, terminated, truncated, info = env.step(action)
        trajectory.append(
            {
                "episode_id": env.truth["episode_id"],
                "step": step_index,
                "action": action,
                "observation": observation,
                "reward": reward,
                "terminated": terminated,
                "truncated": truncated,
            }
        )
        if terminated or truncated:
            break
        try:
            action = generator.send(observation)
        except StopIteration:
            action = {
                "name": "submit",
                "findings": {"episode_id": env.truth["episode_id"], "findings": []},
            }

    generator.close()
    return {
        "trajectory": trajectory,
        "submission": env.submission,
        "inspection_steps": env.inspection_steps,
        "truncated": env.truncated,
    }
