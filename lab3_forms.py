"""Вложенные запросы, условные выражения и собственные типы."""

from tkinter import StringVar, messagebox, ttk

from catalog import I, L, S, comma, identifier
from desktop import Form, required
from querykit import COMPARE, NULL_OPS, REGEX, SIMILAR, filter_value, filtering, predicate


def actions(app):
    return [(label, lambda call=fn: call(app)) for label, fn in (
        ("Вложенный SELECT…", nested),
        ("Строитель CASE…", cases),
        ("Обработка NULL…", null_values),
        ("Пользовательские типы…", types),
    )]


def nested_query(db, outer, inner, quantifier, result_pair, condition, keys):
    column, op, returning = result_pair
    if quantifier not in ("ANY", "ALL", "EXISTS") or op not in COMPARE:
        raise ValueError("Выберите тип сравнения.")
    fragment = S("SELECT {} FROM {} AS sub").format(
        S("1") if quantifier == "EXISTS" else I("sub", returning), db.relation(inner)
    )
    clauses, params = [], []
    if keys[0] or keys[1]:
        if not all(keys):
            raise ValueError("Укажите оба поля для корреляции.")
        clauses.append(S("{} = {}").format(I("outer_row", keys[0]), I("sub", keys[1])))
    field, match, value = condition
    if field:
        clause, params = predicate(I("sub", field), match, value)
        clauses.append(clause)
    if clauses:
        fragment += S(" WHERE ") + S(" AND ").join(clauses)
    if quantifier == "EXISTS":
        check = S("EXISTS ({})").format(fragment)
    else:
        check = S("{} " + op + " " + quantifier + " ({})").format(I("outer_row", column), fragment)
    return S("SELECT outer_row.* FROM {} AS outer_row WHERE {}").format(db.relation(outer), check), params


def nested(app, parent=None):
    form = Form(parent or app.root, "Вложенный SELECT · ANY / ALL / EXISTS", app)
    form.table("outer", "Внешняя таблица")
    form.table("inner", "Внутренняя таблица")
    form.choice("quantifier", "Условие", ("EXISTS", "ANY", "ALL"))
    form.column("outer", "compared", "Внешнее поле для ANY или ALL")
    form.choice("compare", "Оператор сравнения", COMPARE)
    form.column("inner", "returned", "Поле подзапроса для ANY или ALL")
    filtering(form, "inner", operators=COMPARE + NULL_OPS + REGEX + SIMILAR)
    form.column("outer", "left", "Ключ корреляции снаружи", optional=True)
    form.column("inner", "right", "Ключ корреляции внутри", optional=True)
    form.note("Для обычного подзапроса оставьте оба ключа корреляции пустыми.")

    def run():
        query, params = nested_query(app.db, form.get("outer"), form.get("inner"), form.get("quantifier"),
            (form.get("compared"), form.get("compare"), form.get("returned")),
            filter_value(form), (form.get("left"), form.get("right")))
        return app.db.select(query, params)

    form.execute(run, "Проверить")


def case_expression(db, table, branches, fallback):
    parts, values = [], []
    for (field, operator, operand), result in branches:
        if field:
            clause, params = predicate(I(field), operator, operand)
            parts.append(S("WHEN {} THEN %s::text").format(clause))
            values.extend([*params, result])
    required(parts, "хотя бы одно условие WHEN")
    return S("SELECT *, CASE {} ELSE %s::text END AS category FROM {}").format(
        S(" ").join(parts), db.relation(table)
    ), [*values, fallback]


def cases(app):
    form = Form(app.root, "Строитель CASE", app)
    form.table()
    for prefix, label in (("first", "Первое"), ("second", "Второе")):
        filtering(form, "table", prefix, label + " поле WHEN")
        form.entry(prefix + "then", label + " значение THEN")
    form.entry("fallback", "Значение ELSE")
    form.note("CASE выбирает первое выполненное условие. Результат каждой ветки — текст.")

    def run():
        branches = [(filter_value(form, key), form.get(key + "then")) for key in ("first", "second")]
        return app.db.select(*case_expression(app.db, form.get("table"), branches, form.get("fallback")))

    form.execute(run, "Рассчитать")


def null_values(app):
    form = Form(app.root, "Обработка NULL", app)
    form.table()
    form.column("table", "field", "Столбец")
    form.choice("function", "Функция", ("COALESCE", "NULLIF"))
    form.entry("value", "Значение")
    form.note("COALESCE подставляет значение вместо NULL. NULLIF заменяет совпавшее значение на NULL.")

    def run():
        field = I(form.get("field"))
        query = S("SELECT {} AS original, " + form.get("function") + "({}, %s) AS result FROM {}").format(
            field, field, app.db.relation(form.get("table"))
        )
        return app.db.select(query, (form.get("value"),))

    form.execute(run, "Преобразовать")


def types(app):
    form = Form(app.root, "Управление типами", app)
    operations = ("Показать определения", "Создать ENUM", "Создать составной тип",
                  "Создать таблицу с типами", "Переименовать тип", "Добавить метку ENUM", "Удалить тип")
    form.choice("operation", "Операция", operations)

    def configure():
        operation = form.get("operation")
        if operation == operations[0]:
            app.show(form.top, "Типы схемы", ["Имя", "Категория", "Определение"], app.db.custom_types())
        elif operation == operations[1]:
            enum_form(app, form.top)
        elif operation in operations[2:4]:
            field_form(app, form.top, composite=operation == operations[2])
        else:
            modify_type(app, form.top, operations.index(operation) - 4)

    form.button("Открыть", configure)


def create_enum(db, type_name, labels):
    if not labels or len(set(labels)) != len(labels):
        raise ValueError("Укажите разные метки ENUM.")
    ident = identifier(type_name)
    db.run(S("CREATE TYPE {}.{} AS ENUM ({})").format(I(db.schema), ident, comma(map(L, labels))), definition=True)


def enum_form(app, parent):
    form = Form(parent, "Новый ENUM", app)
    form.entry("name", "Имя типа")
    form.entry("labels", "Метки через запятую")

    def create():
        labels = [label.strip() for label in form.get("labels").split(",") if label.strip()]
        create_enum(app.db, form.get("name"), labels)

    form.execute(create, "Создать", changed=True)


def create_fields(db, name, fields, composite):
    required(fields, "хотя бы одно поле")
    definitions = [S("{} {}").format(identifier(field), db.data_type(tp)) for field, tp in fields.items()]
    if not composite:
        definitions.insert(0, S("row_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY"))
    header = "CREATE TYPE {}.{} AS ({})" if composite else "CREATE TABLE {}.{} ({})"
    db.run(S(header).format(I(db.schema), identifier(name), comma(definitions)), definition=True)


def field_form(app, parent, composite):
    db = app.db
    form = Form(parent, "Новый составной тип" if composite else "Новая таблица", app)
    form.entry("name", "Имя объекта")
    form.entry("field", "Имя поля")
    form.choice("type", "Тип поля", db.type_options())
    fields = {}
    chosen = StringVar(master=form.top, value="Полей пока нет")
    form.add("_fields", "Добавленные поля", ttk.Label(form.body, textvariable=chosen, wraplength=380))

    def add():
        field = form.get("field").strip()
        identifier(field)
        if field in fields or not composite and field == "row_id":
            raise ValueError("Поле с таким именем уже существует.")
        fields[field] = form.get("type")
        chosen.set("\n".join(f"{name}: {tp}" for name, tp in fields.items()))
        form.widgets["field"].delete(0, "end")

    def clear():
        fields.clear()
        chosen.set("Полей пока нет")

    form.button("Очистить", clear)
    form.button("Добавить поле", add)
    form.execute(lambda: create_fields(db, form.get("name"), fields, composite), "Создать", changed=True)


def modify_type(app, parent, operation):
    db = app.db
    records = db.custom_types()
    options = [name for name, kind, _ in records if operation != 1 or kind == "ENUM"]
    required(options, "тип, подходящий для операции")
    title = ("Переименовать тип", "Добавить метку ENUM", "Удалить тип")[operation]
    form = Form(parent, title, app)
    form.choice("type", "Тип", options)
    if operation < 2:
        form.entry("value", "Новое имя" if operation == 0 else "Метка")

    def run():
        relation = db.relation(form.get("type"))
        if operation == 0:
            query = S("ALTER TYPE {} RENAME TO {}").format(relation, identifier(form.get("value")))
        elif operation == 1:
            query = S("ALTER TYPE {} ADD VALUE {}").format(relation, L(required(form.get("value"), "метку")))
        else:
            if not messagebox.askyesno(title, f"Удалить тип {form.get('type')}?", parent=form.top):
                return
            query = S("DROP TYPE {}").format(relation)
        db.run(query, definition=True)
        messagebox.showinfo(title, "Изменение сохранено.", parent=form.top)
        form.close()

    form.button("Применить", run)
