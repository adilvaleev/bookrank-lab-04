"""Группировки PostgreSQL, представления и конструктор WITH."""

from tkinter import StringVar, messagebox, ttk

from catalog import I, S, comma, identifier
from desktop import Form, required
from lab2_forms import select_form
from querykit import AGG, COMPARE, NULL_OPS, add_filter, aggregate, column_list, filter_value, filtering, predicate


def actions(app):
    return [(label, lambda call=fn: call(app)) for label, fn in (
        ("Многомерные итоги…", totals),
        ("Представления…", views),
        ("Конструктор WITH…", with_form),
    )]


def totals_query(db, table, mode, dimensions, sets, fn, field, having):
    if mode == "GROUPING SETS":
        required(sets, "хотя бы один набор")
        dimensions = list(dict.fromkeys(field for group in sets for field in group))
        grouping = S("GROUPING SETS ({})").format(
            comma(S("({})").format(comma(map(I, group))) for group in sets)
        )
    elif mode in ("ROLLUP", "CUBE"):
        required(dimensions, "поля группировки")
        grouping = S(mode + "({})").format(comma(map(I, dimensions)))
    else:
        raise ValueError("Выберите вид группировки.")
    metric = aggregate(fn, field)
    columns = list(map(I, dimensions))
    if dimensions:
        columns.append(S("GROUPING({}) AS subtotal_mask").format(comma(map(I, dimensions))))
    columns.append(metric + S(" AS total"))
    query = S("SELECT {} FROM {} GROUP BY {}").format(comma(columns), db.relation(table), grouping)
    op, value = having
    params = []
    if op:
        clause, params = predicate(metric, op, value)
        query += S(" HAVING ") + clause
    return query, params


def totals(app, parent=None):
    db = app.db
    form = Form(parent or app.root, "Многомерные итоги", app)
    form.table()
    form.choice("mode", "Режим", ("ROLLUP", "CUBE", "GROUPING SETS"))
    form.column("table", "dimensions", "Измерения", multiple=True)
    form.choice("fn", "Агрегат", AGG)
    form.column("table", "metric", "Поле агрегата (пусто: COUNT *)", optional=True)
    form.choice("having", "HAVING", COMPARE + NULL_OPS, optional=True)
    form.entry("value", "Значение HAVING")
    form.note("Для GROUPING SETS выберите поля одного набора и добавьте его. Пустой набор даёт общий итог.")
    sets = []
    buffer = StringVar(master=form.top, value="Наборы не заданы")
    form.add("_sets", "Наборы GROUPING SETS", ttk.Label(form.body, textvariable=buffer, wraplength=390))

    def add():
        group = tuple(form.get("dimensions"))
        if group not in sets:
            sets.append(group)
        buffer.set("\n".join(", ".join(fields) or "() · общий итог" for fields in sets))

    def reset(_event=None):
        sets.clear()
        buffer.set("Наборы не заданы")

    form.widgets["table"].bind("<<ComboboxSelected>>", reset, add="+")
    form.button("Сбросить наборы", reset)
    form.button("Добавить набор", add)
    form.execute(lambda: db.select(*totals_query(
        db, form.get("table"), form.get("mode"), form.get("dimensions"), sets, form.get("fn"),
        form.get("metric"), (form.get("having"), form.get("value"))
    )), "Показать")


def save_view(db, name, kind, select, params, replace=False):
    if kind not in ("VIEW", "MATERIALIZED VIEW") or replace and kind != "VIEW":
        raise ValueError("Проверьте тип представления.")
    prefix = "CREATE " + ("OR REPLACE " if replace else "") + kind
    query = S(prefix + " {}.{} AS ").format(I(db.schema), identifier(name)) + select
    db.run(query, params, definition=True)


def views(app):
    db = app.db
    form = Form(app.root, "Представления", app)
    form.choice("view", "Объект", [name for name, _ in db.names(("v", "m"))])
    form.note("Команда «Заменить» сохраняет имена и типы уже существующих полей, как требует PostgreSQL.")

    def reload():
        form.options("view", [name for name, _ in db.names(("v", "m"))])

    def selected():
        name = required(form.get("view"), "представление")
        return name, dict(db.names(("v", "m")))[name]

    def create():
        detail = Form(form.top, "Новое представление", app)
        detail.entry("new", "Имя")
        detail.choice("kind", "Тип", ("VIEW", "MATERIALIZED VIEW"))

        def configure():
            name = detail.get("new").strip()
            identifier(name)
            kind = detail.get("kind")

            def save(query, params):
                save_view(db, name, kind, query, params)
                reload()
                return "Представление создано."

            select_form(app, detail.top, save)

        detail.button("Задать SELECT", configure)

    def replace():
        name, kind = selected()
        if kind != "v":
            raise ValueError("Заменить определение можно у обычного VIEW.")
        select_form(app, form.top, lambda query, params: save_view(db, name, "VIEW", query, params, True))

    def inspect():
        name, _ = selected()
        qualified = db.relation(name).as_string(db.conn)
        headers, rows = db.run(S("SELECT pg_catalog.pg_get_viewdef(%s::regclass, true)"), (qualified,))
        panel = Form(form.top, "Определение представления", app)
        panel.note("Поля: " + ", ".join(db.columns(name)))
        panel.note(rows[0][0] or "Определение отсутствует.")

    def preview():
        name, _ = selected()
        app.show(form.top, name, *db.select(S("SELECT * FROM {}").format(db.relation(name))))

    def refresh():
        name, kind = selected()
        if kind != "m":
            raise ValueError("REFRESH применяется к MATERIALIZED VIEW.")
        db.run(S("REFRESH MATERIALIZED VIEW {}").format(db.relation(name)), definition=True)
        messagebox.showinfo("Материализованное представление", "Данные обновлены.", parent=form.top)

    def drop():
        name, kind = selected()
        if messagebox.askyesno("Подтвердите действие", f"Удалить {name}?", parent=form.top):
            prefix = "DROP MATERIALIZED VIEW {}" if kind == "m" else "DROP VIEW {}"
            db.run(S(prefix).format(db.relation(name)), definition=True)
            reload()

    for label, operation in (
        ("Создать…", create), ("Заменить…", replace), ("Структура…", inspect),
        ("Данные…", preview), ("REFRESH", refresh), ("Удалить…", drop),
    ):
        form.tool(label, operation)


def with_query(db, blocks, result):
    required(blocks, "хотя бы один блок CTE")
    named_queries, params = [], []
    for name, is_cte, source, fields, condition in blocks:
        target = I(source) if is_cte else db.relation(source)
        select = S("SELECT {} FROM {}").format(column_list(fields), target)
        select, values = add_filter(select, condition)
        named_queries.append(S("{} AS ({})").format(I(name), select))
        params.extend(values)
    return S("WITH {} SELECT * FROM {}").format(comma(named_queries), I(result)), params


def with_form(app):
    db = app.db
    form = Form(app.root, "Конструктор WITH", app)
    base = {f"База · {name}": (False, name) for name, _ in db.names()}
    blocks, block_fields = [], {}
    form.entry("name", "Имя нового блока")
    form.choice("source", "Источник", base)
    form.multiple("fields", "Поля (пусто — все)")
    form.choice("col", "Поле WHERE")
    form.choice("op", "Оператор", COMPARE + NULL_OPS)
    form.entry("val", "Значение")
    form.choice("result", "Вывести блок")
    summary = StringVar(master=form.top, value="Блоки пока не добавлены")
    form.add("_blocks", "Цепочка", ttk.Label(form.body, textvariable=summary, wraplength=385))

    def sources():
        return base | {f"WITH · {name}": (True, name) for name in block_fields}

    def load(selected):
        if not selected:
            return []
        is_cte, name = sources()[selected]
        return block_fields[name] if is_cte else db.columns(name)

    form.follow("source", "fields", load)
    form.follow("source", "col", load, optional=True)

    def add():
        name = form.get("name").strip()
        identifier(name)
        if name in block_fields:
            raise ValueError("Блок с таким именем уже есть.")
        source = required(form.get("source"), "источник")
        is_cte, target = sources()[source]
        fields = form.get("fields")
        condition = tuple(form.get(key) for key in ("col", "op", "val"))
        blocks.append((name, is_cte, target, fields, condition))
        block_fields[name] = fields or load(source)
        form.options("source", sources())
        form.options("result", block_fields)
        form.widgets["result"].set(name)
        summary.set("\n".join(f"{label} ← {parent}" for label, _, parent, _, _ in blocks))
        form.widgets["name"].delete(0, "end")

    def clear():
        blocks.clear()
        block_fields.clear()
        form.options("source", base)
        form.widgets["source"].event_generate("<<ComboboxSelected>>")
        form.options("result", ())
        summary.set("Блоки пока не добавлены")

    form.button("Очистить", clear)
    form.button("Добавить блок", add)
    form.execute(lambda: db.select(*with_query(db, blocks, required(form.get("result"), "блок для вывода"))), "Показать")
