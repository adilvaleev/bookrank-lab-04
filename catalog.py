"""PostgreSQL для журнала проверки книжных рекомендаций."""

import logging
from pathlib import Path

import psycopg
from psycopg import ClientCursor, sql

S = sql.SQL
I = sql.Identifier
P = sql.Placeholder
L = sql.Literal
LOG = logging.getLogger("bookrank")
STRATEGIES = ("content", "collaborative", "hybrid")
BUILTINS = ("text", "integer", "bigint", "numeric", "boolean", "date", "timestamp", "text[]")
MESSAGES = {
    "23001": "На запись ссылается другая таблица (RESTRICT).",
    "23502": "Заполните обязательное поле (NOT NULL).",
    "23503": "Проверьте ссылку на связанную запись (FOREIGN KEY).",
    "23505": "Такая запись уже есть (UNIQUE).",
    "23514": "Значение не прошло проверку (CHECK).",
    "22P02": "Значение не подходит по типу.",
    "22007": "Дата должна иметь формат ГГГГ-ММ-ДД.",
    "22008": "Указана некорректная дата.",
    "22003": "Значение выходит за пределы числового типа.",
    "2201B": "Исправьте шаблон регулярного выражения.",
    "42883": "Оператор не подходит для выбранного типа.",
    "2BP01": "От объекта зависят другие объекты.",
    "42501": "У роли PostgreSQL недостаточно прав.",
    "42P01": "Объект не найден. Проверьте схему и имена таблиц.",
}


def identifier(value):
    value = value.strip()
    if not value or len(value.encode("utf-8")) > 63 or "\x00" in value:
        raise ValueError("Укажите имя длиной от 1 до 63 байт.")
    return I(value)


def comma(parts):
    return S(", ").join(parts)


def readable(error):
    if isinstance(error, psycopg.OperationalError):
        return "Проверьте, запущен ли PostgreSQL и верны ли параметры подключения."
    if isinstance(error, psycopg.Error):
        return MESSAGES.get(error.sqlstate) or error.diag.message_primary or str(error)
    return str(error)


class Catalog:
    def __init__(self, number):
        self.schema = f"valeev_books_{number}"
        self.conn = None

    def connect(self, **settings):
        LOG.info("Подключение к PostgreSQL")
        new = psycopg.connect(**settings, connect_timeout=5)
        self.close()
        self.conn = new
        LOG.info("Подключено")

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def relation(self, name):
        return I(self.schema, name)

    def run(self, query, values=(), *, definition=False):
        if self.conn is None or self.conn.closed:
            raise ValueError("Подключитесь к PostgreSQL.")
        LOG.info("SQL: %s", query.as_string(self.conn).split(None, 1)[0])
        try:
            with self.conn.transaction():
                cursor = ClientCursor(self.conn) if definition else self.conn.cursor()
                with cursor:
                    cursor.execute(query, values or None)
                    if cursor.description is None:
                        return [], []
                    return [col.name for col in cursor.description], cursor.fetchall()
        except psycopg.Error as error:
            LOG.error("SQLSTATE %s: %s", error.sqlstate, readable(error))
            raise

    def select(self, query, values=()):
        return self.run(query + S(" LIMIT 1001"), values)

    def install(self):
        source = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        self.run(S(source).format(s=I(self.schema)), definition=True)

    def demo(self):
        query = S("""
            INSERT INTO {e} (code, strategy, features) VALUES
                ('PageVector', 'content', ARRAY['жанр', 'аннотация']),
                ('ReaderCircle', 'collaborative', ARRAY['оценки', 'история']),
                ('BookBlend', 'hybrid', ARRAY['жанр', 'оценки']),
                ('NewShelf', 'hybrid', ARRAY['аннотация'])
            ON CONFLICT (code) DO NOTHING;

            INSERT INTO {b} (engine_id, corpus, checked_on, hit_rate, users_tested, remark)
            SELECT e.engine_id, d.corpus, d.checked_on, d.hit_rate, d.users_tested, d.remark
            FROM (VALUES
                ('PageVector', 'Классика', DATE '2026-10-01', .62, 180, NULL),
                ('PageVector', 'Классика', DATE '2026-10-15', .71, 200, 'Новый словарь'),
                ('ReaderCircle', 'Фантастика', DATE '2026-10-01', .74, 300, NULL),
                ('ReaderCircle', 'Фантастика', DATE '2026-10-15', .82, 320, 'Больше оценок'),
                ('BookBlend', 'Классика', DATE '2026-10-01', .85, 260, NULL),
                ('BookBlend', 'Фантастика', DATE '2026-10-15', .90, 380, 'Смешанная модель'),
                ('BookBlend', 'Классика', DATE '2026-10-20', .87, 275, NULL)
            ) AS d(code, corpus, checked_on, hit_rate, users_tested, remark)
            JOIN {e} e ON e.code = d.code
            ON CONFLICT (engine_id, corpus, checked_on) DO NOTHING;

            INSERT INTO {r} (engine_id, version, released_on)
            SELECT engine_id, '1.0', DATE '2026-10-21' FROM {e} WHERE code = 'BookBlend'
            ON CONFLICT (engine_id, version) DO NOTHING;
        """).format(e=self.relation("engines"), b=self.relation("benchmarks"), r=self.relation("releases"))
        self.run(query, definition=True)

    def names(self, kinds=("r", "p", "v", "m")):
        query = S("""
            SELECT c.relname, c.relkind::text
            FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND c.relkind::text = ANY(%s)
            ORDER BY c.relname
        """)
        return self.run(query, (self.schema, list(kinds)))[1]

    def columns(self, table):
        query = S("""
            SELECT a.attname
            FROM pg_catalog.pg_attribute a
            WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
        """)
        qualified = self.relation(table).as_string(self.conn)
        return [row[0] for row in self.run(query, (qualified,))[1]]

    def custom_types(self):
        query = S("""
            SELECT t.typname, CASE WHEN t.typtype = 'e' THEN 'ENUM' ELSE 'COMPOSITE' END,
                   CASE WHEN t.typtype = 'e' THEN (
                     SELECT string_agg(quote_literal(enumlabel), ', ' ORDER BY enumsortorder)
                     FROM pg_catalog.pg_enum WHERE enumtypid = t.oid
                   ) ELSE (
                     SELECT string_agg(quote_ident(attname) || ' ' ||
                         pg_catalog.format_type(atttypid, atttypmod), ', ' ORDER BY attnum)
                     FROM pg_catalog.pg_attribute
                     WHERE attrelid = t.typrelid AND attnum > 0 AND NOT attisdropped
                   ) END
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
            LEFT JOIN pg_catalog.pg_class c ON c.oid = t.typrelid
            WHERE n.nspname = %s AND (t.typtype = 'e' OR c.relkind = 'c')
            ORDER BY t.typname
        """)
        return self.run(query, (self.schema,))[1]

    def type_options(self):
        return (*BUILTINS, *(f"Тип · {row[0]}" for row in self.custom_types()))

    def data_type(self, label):
        if label in BUILTINS:
            return S(label)
        if label.startswith("Тип · "):
            return self.relation(label.removeprefix("Тип · "))
        raise ValueError("Выберите тип данных.")

    def constraints(self, table):
        query = S("""
            SELECT conname FROM pg_catalog.pg_constraint
            WHERE conrelid = %s::regclass AND contype IN ('c', 'u', 'f') ORDER BY conname
        """)
        return [row[0] for row in self.run(query, (self.relation(table).as_string(self.conn),))[1]]

    def insert(self, table, fields):
        self.run(S("INSERT INTO {} ({}) VALUES ({})").format(
            self.relation(table), comma(map(I, fields)), comma(P() for _ in fields)
        ), list(fields.values()))

    def overview(self, strategy="", corpus="", since="", minimum=""):
        query = S("""
            SELECT b.benchmark_id, e.code, e.strategy, b.corpus, b.checked_on,
                   b.hit_rate, b.users_tested, b.remark
            FROM {} b JOIN {} e USING (engine_id)
        """).format(self.relation("benchmarks"), self.relation("engines"))
        predicates, values = [], []
        for clause, value in (("e.strategy = %s", strategy), ("b.corpus ILIKE %s", corpus),
                              ("b.checked_on >= %s", since), ("b.hit_rate >= %s", minimum)):
            if value:
                predicates.append(S(clause))
                values.append(f"%{value}%" if clause.startswith("b.corpus") else value)
        if predicates:
            query += S(" WHERE ") + S(" AND ").join(predicates)
        return self.select(query + S(" ORDER BY b.checked_on, b.benchmark_id"), values)

    def verify_fk(self):
        query = S("""
            INSERT INTO {} (engine_id, corpus, checked_on, hit_rate, users_tested)
            SELECT absent, 'Проверка ссылки', CURRENT_DATE, 0.9, 10
            FROM generate_series(-100, -1) AS candidates(absent)
            WHERE NOT EXISTS (SELECT 1 FROM {} WHERE engine_id = absent)
            LIMIT 1
        """).format(self.relation("benchmarks"), self.relation("engines"))
        try:
            with self.conn.transaction():
                self.run(query)
                raise ValueError("Нарушение не обнаружено. Пробная операция отменена.")
        except psycopg.errors.ForeignKeyViolation:
            return "Внешний ключ отклонил запись. Транзакция отменена."
