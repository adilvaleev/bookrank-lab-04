"""Формы и табличный вывод на Tkinter."""

import getpass
import logging
import os
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

import psycopg

from catalog import Catalog, LOG, STRATEGIES, I, S, readable


def required(value, label):
    if not value or isinstance(value, str) and not value.strip():
        raise ValueError(f"Укажите {label}.")
    return value


def window(parent, title, size):
    panel = tk.Toplevel(parent)
    panel.title(title)
    panel.geometry(size)
    panel.transient(parent)
    previous = parent.grab_current()

    def close():
        panel.destroy()
        if previous is not None and previous.winfo_exists():
            previous.grab_set()

    panel.protocol("WM_DELETE_WINDOW", close)
    panel.bind("<Escape>", lambda _event: close())
    panel.wait_visibility()
    panel.grab_set()
    return panel, close


class Form:
    def __init__(self, parent, title, service):
        self.top, self.close = window(parent, title, "690x555")
        self.service = service
        self.widgets = {}
        self.key_order = []
        shell = ttk.Frame(self.top, padding=14)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text=title, font=("TkDefaultFont", 15, "bold")).pack(anchor="w", pady=(0, 10))
        self.footer = ttk.Frame(shell)
        self.footer.pack(side="bottom", fill="x", pady=(10, 0))
        ttk.Button(self.footer, text="Закрыть", command=self.close).pack(side="right")
        content = ttk.Frame(shell)
        content.pack(fill="both", expand=True)
        canvas = tk.Canvas(content, highlightthickness=0, background=ttk.Style().lookup("TFrame", "background"))
        scrollbar = ttk.Scrollbar(content, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(canvas)
        self.body.columnconfigure(1, weight=1)
        frame_id = canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(frame_id, width=event.width))

    def add(self, key, label, field):
        row = len(self.key_order)
        self.key_order.append(key)
        self.widgets[key] = field
        ttk.Label(self.body, text=label, wraplength=225).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=4)
        field.grid(row=row, column=1, sticky="ew", pady=3, padx=(0, 8))
        return field

    def entry(self, key, label, initial="", secret=False):
        widget = ttk.Entry(self.body, show="•" if secret else "")
        widget.insert(0, initial)
        return self.add(key, label, widget)

    def choice(self, key, label, options=(), optional=False):
        widget = ttk.Combobox(self.body, state="readonly")
        self.add(key, label, widget)
        self.options(key, options, optional)
        return widget

    def multiple(self, key, label, options=()):
        widget = tk.Listbox(self.body, height=4, selectmode="multiple", exportselection=False)
        self.add(key, label, widget)
        self.options(key, options)
        return widget

    def note(self, text):
        label = ttk.Label(self.body, text=text, wraplength=380, justify="left")
        self.add(f"_note{len(self.key_order)}", "", label)

    def get(self, key):
        widget = self.widgets[key]
        if isinstance(widget, tk.Listbox):
            return [widget.get(i) for i in widget.curselection()]
        return widget.get()

    def options(self, key, values, optional=False):
        widget = self.widgets[key]
        current = self.get(key)
        values = tuple(values)
        if isinstance(widget, tk.Listbox):
            widget.delete(0, "end")
            for index, value in enumerate(values):
                widget.insert("end", value)
                if value in current:
                    widget.selection_set(index)
        else:
            values = ("", *values) if optional else values
            widget.configure(values=values)
            widget.set(current if current in values else values[0] if values else "")

    def follow(self, source, target, load, optional=False):
        def update(_event=None):
            self.service.safe(self.top, lambda: self.options(target, load(self.get(source)), optional))

        self.widgets[source].bind("<<ComboboxSelected>>", update, add="+")
        update()

    def table(self, key="table", label="Таблица", tables_only=False):
        kinds = ("r", "p") if tables_only else ("r", "p", "v", "m")
        tables = [name for name, _ in self.service.db.names(kinds)]
        if not tables:
            self.close()
            raise ValueError("Сначала создайте схему и загрузите данные.")
        return self.choice(key, label, tables)

    def column(self, source, key, label, optional=False, multiple=False):
        if multiple:
            self.multiple(key, label)
        else:
            self.choice(key, label)
        self.follow(source, key, self.service.db.columns, optional)

    def button(self, text, action):
        ttk.Button(self.footer, text=text, command=lambda: self.service.safe(self.top, action)).pack(side="right", padx=7)

    def tool(self, text, action):
        control = ttk.Button(self.body, text=text, command=lambda: self.service.safe(self.top, action))
        self.add(f"_tool{len(self.key_order)}", "", control)

    def execute(self, function, text="Выполнить", changed=False):
        def action():
            result = function()
            if isinstance(result, tuple):
                self.service.show(self.top, self.top.title(), *result)
            elif changed:
                messagebox.showinfo(self.top.title(), result or "Изменение сохранено.", parent=self.top)
                self.close()

        self.button(text, action)


class Desktop:
    def __init__(self, root, level):
        self.root = root
        self.level = level
        self.db = Catalog(level)
        self.connection_fields = {"host": os.getenv("PGHOST", "localhost"),
                                  "port": os.getenv("PGPORT", "5432"),
                                  "dbname": os.getenv("PGDATABASE", "postgres"),
                                  "user": os.getenv("PGUSER", getpass.getuser())}
        root.title(f"Книжные рекомендации · ЛР {level} · Валеев А.А.")
        root.geometry("760x500")
        root.minsize(630, 430)
        root.protocol("WM_DELETE_WINDOW", self.finish)
        shell = ttk.Frame(root, padding=18)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Журнал книжных рекомендаций", font=("TkDefaultFont", 19, "bold")).pack(anchor="w")
        ttk.Label(shell, text=f"Валеев А.А.   ·   Лабораторная работа №{level}").pack(anchor="w", pady=(4, 12))
        toolbar = ttk.Frame(shell)
        toolbar.pack(fill="x", pady=(0, 12))
        ttk.Button(toolbar, text="Подключение…", command=self.connect_form).pack(side="left")
        ttk.Button(toolbar, text="Отключиться", command=self.disconnect).pack(side="left", padx=8)
        self.status = tk.StringVar(value="PostgreSQL: подключение не установлено")
        ttk.Label(toolbar, textvariable=self.status).pack(side="right")

        notebook = ttk.Notebook(shell)
        notebook.pack(fill="both", expand=True)
        self.buttons = []
        self.screen(notebook, "Данные", self.core())
        for number, tab in [(2, "Конструкторы"), (3, "Выражения"), (4, "Отчёты"), (5, "Окна")]:
            if level >= number:
                from importlib import import_module
                module = import_module(f"lab{number}_forms")
                self.screen(notebook, tab, module.actions(self))
        self.disable(True)

    def screen(self, notebook, label, commands):
        tab = ttk.Frame(notebook, padding=12)
        notebook.add(tab, text=label)
        tab.columnconfigure((0, 1), weight=1, uniform="operations")
        for index, (title, command) in enumerate(commands):
            button = ttk.Button(tab, text=title, command=lambda fn=command: self.safe(self.root, fn))
            button.grid(column=index % 2, row=index // 2, sticky="ew", padx=4, pady=4)
            self.buttons.append(button)

    def disable(self, disabled):
        for button in self.buttons:
            button.state(["disabled"] if disabled else ["!disabled"])

    def safe(self, parent, function):
        try:
            return function()
        except (psycopg.Error, ValueError) as error:
            LOG.error("%s", readable(error))
            host = parent if parent.winfo_exists() else self.root
            messagebox.showerror("Операция не выполнена", readable(error), parent=host)
            return None

    def connect_form(self):
        form = Form(self.root, "Подключение к PostgreSQL", self)
        for name, label in (("host", "Сервер"), ("port", "Порт"), ("dbname", "База"), ("user", "Роль")):
            form.entry(name, label, self.connection_fields[name])
        form.entry("password", "Пароль", secret=True)

        def connect():
            config = {name: required(form.get(name).strip(), name) for name in self.connection_fields}
            if not 1 <= int(config["port"]) <= 65535:
                raise ValueError("Порт должен быть от 1 до 65535.")
            self.db.connect(**config, password=form.get("password") or None)
            self.connection_fields = config
            self.status.set(f"Подключено · {self.db.schema}")
            self.disable(False)
            form.close()

        form.button("Подключиться", connect)

    def disconnect(self):
        self.db.close()
        self.disable(True)
        self.status.set("PostgreSQL: подключение не установлено")

    def finish(self):
        self.db.close()
        self.root.destroy()

    def core(self):
        return [
            ("Создать схему", lambda: self.done(self.db.install, "Схема и таблицы подготовлены.")),
            ("Загрузить демоданные", lambda: self.done(self.db.demo, "Добавлены учебные записи.")),
            ("Новый алгоритм…", lambda: self.add_entry("engines", "Новый алгоритм")),
            ("Новая проверка…", lambda: self.add_entry("benchmarks", "Новая проверка")),
            ("Новая версия…", lambda: self.add_entry("releases", "Новая версия")),
            ("Сводка испытаний…", self.overview_form),
            ("Проверить внешний ключ", lambda: self.done(self.db.verify_fk)),
        ]

    def done(self, callback, text=""):
        result = callback()
        messagebox.showinfo("Журнал рекомендаций", result or text, parent=self.root)

    def add_entry(self, table, title):
        choices = {}
        if table != "engines":
            query = S("SELECT code, engine_id FROM {} ORDER BY code").format(self.db.relation("engines"))
            choices = dict(self.db.run(query)[1])
            required(choices, "хотя бы один алгоритм")
        form = Form(self.root, title, self)
        if table == "engines":
            form.entry("code", "Название")
            form.choice("strategy", "Стратегия", STRATEGIES)
            form.entry("features", "Признаки через запятую")
            form.choice("enabled", "Активен", ("Да", "Нет"))
        else:
            form.choice("engine", "Алгоритм", choices)
            if table == "benchmarks":
                form.entry("corpus", "Набор книг")
                form.entry("checked_on", "Дата · ГГГГ-ММ-ДД")
                form.entry("hit_rate", "Доля попаданий · от 0 до 1")
                form.entry("users_tested", "Участников")
                form.entry("remark", "Заметка (необязательно)")
            else:
                form.entry("version", "Версия")
                form.entry("released_on", "Дата · ГГГГ-ММ-ДД")

        def save():
            values = {name: form.get(name).strip() or None for name in form.key_order}
            if table == "engines":
                values["features"] = [item.strip() for item in (values["features"] or "").split(",") if item.strip()]
                values["enabled"] = values["enabled"] == "Да"
            else:
                values["engine_id"] = choices[values.pop("engine")]
            self.db.insert(table, values)

        form.execute(save, "Добавить", changed=True)

    def overview_form(self):
        form = Form(self.root, "Сводка испытаний", self)
        form.choice("strategy", "Стратегия", STRATEGIES, optional=True)
        form.entry("corpus", "Набор книг содержит")
        form.entry("since", "Дата с · ГГГГ-ММ-ДД")
        form.entry("minimum", "Минимальная доля попаданий")
        filters = tuple(form.key_order)
        form.execute(lambda: self.db.overview(*(form.get(key).strip() for key in filters)), "Показать")
        if self.level >= 2:
            from lab2_forms import select_form, strings
            form.tool("Конструктор SELECT…", lambda: select_form(self, form.top))
            form.tool("Строковые функции…", lambda: strings(self, form.top))
        if self.level >= 3:
            from lab3_forms import nested
            form.tool("Вложенный SELECT…", lambda: nested(self, form.top))

    def show(self, parent, title, headers, rows):
        panel, close = window(parent, title, "1020x490")
        shell = ttk.Frame(panel, padding=12)
        shell.pack(fill="both", expand=True)
        bar = ttk.Frame(shell)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Поиск по загруженным строкам").pack(side="left")
        text = tk.StringVar()
        ttk.Entry(bar, textvariable=text).pack(side="left", fill="x", expand=True, padx=9)
        status = ttk.Label(bar)
        status.pack(side="right")
        footer = ttk.Frame(shell)
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text="Закрыть", command=close).pack(side="right")
        body = ttk.Frame(shell)
        body.pack(fill="both", expand=True, pady=(0, 8))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        keys = tuple(f"c{i}" for i in range(len(headers)))
        tree = ttk.Treeview(body, columns=keys, show="headings")
        tree.grid(column=0, row=0, sticky="nsew")
        for orientation, axis, row, col, sticky in [
            ("vertical", "y", 0, 1, "ns"), ("horizontal", "x", 1, 0, "ew"),
        ]:
            scrollbar = ttk.Scrollbar(body, orient=orientation, command=getattr(tree, axis + "view"))
            scrollbar.grid(row=row, column=col, sticky=sticky)
            tree.configure(**{axis + "scrollcommand": scrollbar.set})
        order = [None, False]

        def refresh(*_args):
            tree.delete(*tree.get_children())
            needle = text.get().casefold()
            displayed = [(row, tuple("NULL" if val is None else str(val) for val in row)) for row in rows[:1000]]
            displayed = [(row, values) for row, values in displayed if any(needle in val.casefold() for val in values)]
            col, reverse = order
            if col is not None:
                existing = [item for item in displayed if item[0][col] is not None]
                nulls = [item for item in displayed if item[0][col] is None]
                try:
                    existing.sort(key=lambda item: item[0][col], reverse=reverse)
                except TypeError:
                    existing.sort(key=lambda item: item[1][col].casefold(), reverse=reverse)
                displayed = existing + nulls
            for _, row in displayed:
                tree.insert("", "end", values=row)
            status.configure(text=f"Строк: {len(displayed)}" + (" / первые 1000" if len(rows) > 1000 else ""))

        def sort(col):
            order[:] = [col, not order[1] if order[0] == col else False]
            refresh()

        for index, header in enumerate(headers):
            tree.heading(keys[index], text=header, command=lambda col=index: sort(col))
            tree.column(keys[index], width=max(95, min(205, 10 * len(header))), stretch=False)
        text.trace_add("write", refresh)
        refresh()


def launch(level):
    logging.basicConfig(filename=Path(__file__).with_name("bookrank.log"),
                        encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    root = tk.Tk()
    Desktop(root, level)
    root.mainloop()
