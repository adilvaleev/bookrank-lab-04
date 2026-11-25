"""Общие фрагменты запросов и поля конструкторов."""

from catalog import S, I, comma

COMPARE = ("=", "<>", ">", ">=", "<", "<=")
NULL_OPS = ("IS NULL", "IS NOT NULL")
REGEX = ("LIKE", "~", "~*", "!~", "!~*")
SIMILAR = ("SIMILAR TO", "NOT SIMILAR TO")
AGG = ("COUNT", "SUM", "AVG", "MIN", "MAX")


def filtering(form, source, prefix="f", label="Поле WHERE", operators=COMPARE + NULL_OPS):
    form.column(source, prefix + "col", label, optional=True)
    form.choice(prefix + "op", "Оператор", operators)
    form.entry(prefix + "val", "Значение / шаблон")


def filter_value(form, prefix="f"):
    return tuple(form.get(prefix + key) for key in ("col", "op", "val"))


def predicate(column, operator, value):
    if operator in COMPARE:
        return S("{} " + operator + " %s").format(column), [value]
    if operator in NULL_OPS:
        return S("{} " + operator).format(column), []
    if operator in REGEX + SIMILAR:
        return S("CAST({} AS text) " + operator + " %s").format(column), [value]
    raise ValueError("Выберите оператор.")


def add_filter(query, triple, alias=None):
    field, op, value = triple
    if not field:
        return query, []
    column = I(alias, field) if alias else I(field)
    clause, params = predicate(column, op, value)
    return query + S(" WHERE ") + clause, params


def column_list(fields):
    return comma(map(I, fields)) if fields else S("*")


def aggregate(function, field):
    if function not in AGG or not field and function != "COUNT":
        raise ValueError("Выберите столбец для агрегата. Только COUNT поддерживает все строки.")
    return S(function + "({})").format(I(field) if field else S("*"))
