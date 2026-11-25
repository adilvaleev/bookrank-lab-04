"""Выборки и изменение таблиц."""

from tkinter import messagebox

from catalog import I, S, comma, identifier
from desktop import Form, required
from querykit import AGG, COMPARE, NULL_OPS, REGEX, SIMILAR, add_filter, aggregate, column_list, filter_value, filtering, predicate


def actions(app):
    return [(label, lambda call=fn: call(app)) for label, fn in (
        ("Конструктор SELECT…", select_form),
        ("Мастер соединений…", joins),
        ("Поиск по шаблону…", pattern),
        ("Строковые функции…", strings),
        ("Изменить таблицу (ALTER)…", alter_picker),
    )]


def selected_query(db, table, fields, filters, groups, function, aggregate_field, having, order, direction):
    metric = aggregate(function, aggregate_field) if function else None
    fields = list(groups) if groups or metric is not None else list(fields)
    if metric is not None:
        fields_sql = comma([*(I(field) for field in fields), metric + S(" AS result")])
    else:
        fields_sql = column_list(fields)
    query = S("SELECT {} FROM {}").format(fields_sql, db.relation(table))
    clauses, params = [], []
    for field, op, value in filters:
        if field:
            fragment, values = predicate(I(field), op, value)
            clauses.append(fragment)
            params.extend(values)
    if clauses:
        query += S(" WHERE ") + S(" AND ").join(clauses)
    if groups:
        query += S(" GROUP BY ") + column_list(groups)
    operator, value = having
    if operator:
        if metric is None:
            raise ValueError("HAVING требует агрегатной функции.")
        clause, values = predicate(metric, operator, value)
        query += S(" HAVING ") + clause
        params.extend(values)
    if order:
        if (groups or metric is not None or fields) and order not in fields and not (order == "result" and metric):
            raise ValueError("Выберите выходной столбец или result для сортировки.")
        query += S(" ORDER BY {} " + direction).format(I(order))
    return query, params


def select_form(app, parent=None, save=None):
    db = app.db
    form = Form(parent or app.root, "Конструктор SELECT", app)
    form.table()
    form.column("table", "fields", "Поля вывода (пусто — все)", multiple=True)
    ops = COMPARE + NULL_OPS + REGEX + (SIMILAR if app.level >= 3 else ())
    filtering(form, "table", "a", operators=ops)
    filtering(form, "table", "b", "Второе поле WHERE (AND)", operators=ops)
    form.column("table", "groups", "Поля GROUP BY", multiple=True)
    form.choice("function", "Агрегат", AGG, optional=True)
    form.column("table", "agg_field", "Поле агрегата (пусто: COUNT *)", optional=True)
    form.choice("having", "HAVING для агрегата", COMPARE + NULL_OPS, optional=True)
    form.entry("hvalue", "Значение HAVING")
    # Список включает псевдоним только для случая агрегирования.
    form.choice("order", "Поле ORDER BY")
    form.follow("table", "order", lambda table: [*db.columns(table), "result"], optional=True)
    form.choice("direction", "Направление", ("ASC", "DESC"))

    def build():
        return selected_query(db, form.get("table"), form.get("fields"), (filter_value(form, "a"), filter_value(form, "b")),
                              form.get("groups"), form.get("function"), form.get("agg_field"),
                              (form.get("having"), form.get("hvalue")), form.get("order"), form.get("direction"))

    form.execute(lambda: db.select(*build()), "Показать")
    if save:
        form.execute(lambda: save(*build()), "Сохранить определение", changed=True)
    else:
        if app.level >= 4:
            from lab4_forms import totals
            form.tool("Многомерные итоги…", lambda: totals(app, form.top))
        if app.level >= 5:
            from lab5_forms import picker
            form.tool("Оконные функции…", lambda: picker(app, form.top))


def joins(app):
    db = app.db
    form = Form(app.root, "Мастер соединений", app)
    form.table("left", "Таблица слева")
    form.column("left", "left_key", "Ключ слева")
    form.table("right", "Таблица справа")
    form.column("right", "right_key", "Ключ справа")
    form.choice("kind", "Способ", ("INNER", "LEFT", "RIGHT", "FULL"))
    filtering(form, "left", label="Поле WHERE слева")
    form.column("right", "order", "Поле ORDER BY справа", optional=True)
    form.choice("direction", "Направление", ("ASC", "DESC"))

    def run():
        left, right = form.get("left"), form.get("right")
        projection = []
        for alias, table in (("a", left), ("b", right)):
            for index, column in enumerate(db.columns(table), 1):
                projection.append(S("{} AS {}").format(I(alias, column), I(f"{alias}{index}_{column[:14]}")))
        query = S("SELECT {} FROM {} a " + form.get("kind") + " JOIN {} b ON {} = {}").format(
            comma(projection), db.relation(left), db.relation(right), I("a", form.get("left_key")), I("b", form.get("right_key"))
        )
        query, values = add_filter(query, filter_value(form), "a")
        if form.get("order"):
            query += S(" ORDER BY {} " + form.get("direction")).format(I("b", form.get("order")))
        return db.select(query, values)

    form.execute(run, "Соединить")


def pattern(app):
    form = Form(app.root, "Поиск по шаблону", app)
    form.table()
    form.column("table", "column", "Столбец")
    form.choice("op", "Тип поиска", REGEX + (SIMILAR if app.level >= 3 else ()))
    form.entry("value", "Шаблон")
    form.note("LIKE использует % для последовательности и _ для одного символа.")

    def run():
        clause, params = predicate(I(form.get("column")), form.get("op"), form.get("value"))
        query = S("SELECT * FROM {} WHERE {}").format(app.db.relation(form.get("table")), clause)
        return app.db.select(query, params)

    form.execute(run, "Найти")


def strings(app, parent=None):
    form = Form(parent or app.root, "Строковые функции", app)
    form.table()
    form.column("table", "field", "Столбец")
    form.choice("function", "Функция", ("UPPER", "LOWER", "TRIM", "SUBSTRING", "LPAD", "RPAD", "CONCAT"))
    form.entry("start", "SUBSTRING: начало", "1")
    form.entry("length", "SUBSTRING / LPAD / RPAD: длина", "10")
    form.entry("text", "Заполнитель / добавляемый текст", "-")
    form.column("table", "other", "CONCAT: второй столбец (или текст)", optional=True)

    def run():
        function = form.get("function")
        field = S("CAST({} AS text)").format(I(form.get("field")))
        values = []
        if function == "SUBSTRING":
            expression = S("substring({} FROM %s FOR %s)").format(field)
            values = [int(form.get("start")), int(form.get("length"))]
        elif function in ("LPAD", "RPAD"):
            expression = S(function + "({}, %s, %s)").format(field)
            values = [int(form.get("length")), form.get("text")]
        elif function == "CONCAT":
            other = form.get("other")
            expression = S("concat({}, {})").format(field, I(other) if other else S("%s::text"))
            values = [] if other else [form.get("text")]
        else:
            expression = S(function + "({})").format(field)
        query = S("SELECT {} AS original, {} AS transformed FROM {}").format(field, expression, app.db.relation(form.get("table")))
        return app.db.select(query, values)

    form.execute(run, "Преобразовать")


ALTER = (
    "Добавить столбец", "Удалить столбец", "Переименовать столбец", "Переименовать таблицу",
    "Изменить тип столбца", "Добавить NOT NULL", "Снять NOT NULL", "Добавить CHECK",
    "Добавить UNIQUE", "Добавить FOREIGN KEY", "Удалить CHECK / UNIQUE / FOREIGN KEY",
)
ACTIONS_FK = ("RESTRICT", "CASCADE", "SET NULL", "NO ACTION")


def alter_picker(app):
    panel = Form(app.root, "Операции ALTER TABLE", app)
    panel.choice("operation", "Операция", ALTER)
    panel.button("Настроить", lambda: alter(app, panel.top, panel.get("operation")))


def alter(app, parent, operation):
    db = app.db
    form = Form(parent, operation, app)
    form.table(tables_only=True)
    if operation not in (ALTER[0], ALTER[3], ALTER[10]):
        form.column("table", "column", "Столбец")
    if operation in (ALTER[0], ALTER[2], ALTER[3]):
        form.entry("new", "Новое имя")
    if operation in (ALTER[0], ALTER[4]):
        form.choice("type", "Тип", db.type_options())
    if operation in ALTER[7:10]:
        form.entry("constraint", "Имя ограничения")
    if operation == ALTER[7]:
        form.choice("operator", "Оператор CHECK", COMPARE + NULL_OPS)
        form.entry("value", "Значение")
    elif operation == ALTER[9]:
        form.table("reference", "Таблица назначения", tables_only=True)
        form.column("reference", "reference_column", "Столбец назначения")
        for key in ("DELETE", "UPDATE"):
            form.choice(key, "ON " + key, ACTIONS_FK)
    elif operation == ALTER[10]:
        form.choice("constraint", "Ограничение")
        form.follow("table", "constraint", db.constraints)

    def run():
        if operation in (ALTER[1], ALTER[6], ALTER[10]) and not messagebox.askyesno(
                "Подтвердите действие", f"Применить «{operation}»?", parent=form.top):
            return
        apply_alter(db, operation, {key: form.get(key) for key in form.key_order})
        messagebox.showinfo(operation, "Изменение сохранено.", parent=form.top)
        form.close()

    form.button("Применить", run)


def apply_alter(db, operation, values):
    table = db.relation(values["table"])
    col = identifier(values["column"]) if "column" in values else None
    new = identifier(values["new"]) if "new" in values else None
    data_type = db.data_type(values["type"]) if "type" in values else None
    constraint = identifier(values["constraint"]) if "constraint" in values else None
    params = []
    if operation == ALTER[0]:
        command = S("ADD COLUMN {} {}").format(new, data_type)
    elif operation == ALTER[1]:
        command = S("DROP COLUMN {}").format(col)
    elif operation == ALTER[2]:
        command = S("RENAME COLUMN {} TO {}").format(col, new)
    elif operation == ALTER[3]:
        command = S("RENAME TO {}").format(new)
    elif operation == ALTER[4]:
        command = S("ALTER COLUMN {} TYPE {} USING {}::{}").format(col, data_type, col, data_type)
    elif operation in ALTER[5:7]:
        command = S("ALTER COLUMN {} " + ("SET" if operation == ALTER[5] else "DROP") + " NOT NULL").format(col)
    elif operation == ALTER[7]:
        expression, params = predicate(col, values["operator"], values["value"])
        command = S("ADD CONSTRAINT {} CHECK ({})").format(constraint, expression)
    elif operation == ALTER[8]:
        command = S("ADD CONSTRAINT {} UNIQUE ({})").format(constraint, col)
    elif operation == ALTER[9]:
        delete, update = values["DELETE"], values["UPDATE"]
        if delete not in ACTIONS_FK or update not in ACTIONS_FK:
            raise ValueError("Выберите поведение внешнего ключа.")
        command = S("ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) ON DELETE {} ON UPDATE {}").format(
            constraint, col, db.relation(values["reference"]), identifier(values["reference_column"]), S(delete), S(update)
        )
    else:
        command = S("DROP CONSTRAINT {}").format(constraint)
    db.run(S("ALTER TABLE {} ").format(table) + command, params, definition=True)
