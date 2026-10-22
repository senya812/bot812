import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "shop.db")


@contextmanager
def connect():
    """Соединение с включёнными внешними ключами; commit/rollback и close — автоматически."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                name TEXT NOT NULL,
                description TEXT,
                price INTEGER,
                photo_id TEXT,
                FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS cart (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
            CREATE TABLE IF NOT EXISTS stock (
                product_id INTEGER NOT NULL,
                size TEXT NOT NULL,
                qty INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
                position INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (product_id, size),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            -- Журнал без внешнего ключа: история остаётся, даже если товар удалили.
            CREATE TABLE IF NOT EXISTS stock_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_id INTEGER,
                product_id INTEGER NOT NULL,
                size TEXT NOT NULL,
                delta INTEGER NOT NULL,
                qty_after INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                undone INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_stock_log_admin ON stock_log(admin_id, id);
            -- Сообщения «ленты» каталога, которые бот потом удаляет по кнопке «Назад».
            CREATE TABLE IF NOT EXISTS feed_msgs (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_feed_chat ON feed_msgs(chat_id);
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
        ''')
        # Миграция старых баз: убираем «осиротевшие» и дублирующиеся записи образа,
        # затем запрещаем дубли на уровне БД.
        conn.execute("DELETE FROM cart WHERE product_id NOT IN (SELECT id FROM products)")
        conn.execute(
            "DELETE FROM cart WHERE id NOT IN (SELECT MIN(id) FROM cart GROUP BY user_id, product_id)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_cart_user_product ON cart(user_id, product_id)"
        )
        # Telegram всё равно не даёт удалять сообщения старше 48 часов — старые записи не нужны.
        conn.execute("DELETE FROM feed_msgs WHERE ts < datetime('now', '-2 days')")


# --- ПОЛЬЗОВАТЕЛИ / CRM ---

def register_user(user_id: int, username, first_name):
    with connect() as conn:
        conn.execute(
            '''INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,
                                                  first_name = excluded.first_name''',
            (user_id, username, first_name),
        )


def get_all_users():
    with connect() as conn:
        return [row[0] for row in conn.execute("SELECT user_id FROM users")]


def get_crm_stats():
    """(всего клиентов, всего товаров, клиентов с непустым образом)"""
    with connect() as conn:
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        carts = conn.execute("SELECT COUNT(DISTINCT user_id) FROM cart").fetchone()[0]
    return users, products, carts


# --- КАТЕГОРИИ ---

def add_category(name: str) -> int:
    with connect() as conn:
        return conn.execute("INSERT INTO categories (name) VALUES (?)", (name,)).lastrowid


def get_categories():
    with connect() as conn:
        return conn.execute("SELECT id, name FROM categories ORDER BY id").fetchall()


def get_category(category_id: int):
    """Название категории или None, если её нет."""
    with connect() as conn:
        row = conn.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    return row[0] if row else None


def get_category_name(category_id: int):
    return get_category(category_id) or "Неизвестно"


def count_products(category_id: int) -> int:
    with connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM products WHERE category_id = ?", (category_id,)
        ).fetchone()[0]


def delete_category(category_id: int):
    """Удаляет категорию, её товары и эти товары из всех образов (каскадом)."""
    with connect() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))


# --- ТОВАРЫ ---

def add_product(category_id: int, name: str, description: str, price: int, photo_id: str) -> int:
    with connect() as conn:
        return conn.execute(
            "INSERT INTO products (category_id, name, description, price, photo_id) VALUES (?, ?, ?, ?, ?)",
            (category_id, name, description, price, photo_id),
        ).lastrowid


def get_products_by_category(category_id: int):
    with connect() as conn:
        return conn.execute(
            "SELECT id, name FROM products WHERE category_id = ? ORDER BY id", (category_id,)
        ).fetchall()


def get_product_details(product_id: int):
    """(category_id, name, description, price, photo_id) или None."""
    with connect() as conn:
        return conn.execute(
            "SELECT category_id, name, description, price, photo_id FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()


def delete_product(product_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


# --- ОБРАЗ (бывшая корзина) ---

def add_to_cart(user_id: int, product_id: int) -> bool:
    """True — добавили, False — вещь уже была в образе.
    Если товара не существует, бросит sqlite3.IntegrityError."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO cart (user_id, product_id) VALUES (?, ?)", (user_id, product_id)
        )
        return cur.rowcount > 0


def remove_from_cart(user_id: int, product_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id))


def is_in_cart(user_id: int, product_id: int) -> bool:
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM cart WHERE user_id = ? AND product_id = ?", (user_id, product_id)
        ).fetchone() is not None


def cart_count(user_id: int) -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM cart WHERE user_id = ?", (user_id,)).fetchone()[0]


def get_cart_items(user_id: int):
    """[(cart_id, name, price, product_id), ...] в порядке добавления."""
    with connect() as conn:
        return conn.execute(
            '''SELECT cart.id, products.name, products.price, products.id
               FROM cart JOIN products ON cart.product_id = products.id
               WHERE cart.user_id = ? ORDER BY cart.id''',
            (user_id,),
        ).fetchall()


def clear_cart(user_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))


# --- РАЗМЕРЫ И ОСТАТКИ ---
# У товара без строк в stock размеры не ведутся: клиент их не видит, считается «в наличии».

def touch_admin(user_id: int, name: str):
    """Запоминает имя админа, чтобы в журнале было «Анна», а не число (админ мог ни разу не нажать /start)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO admins (user_id, name) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET name = excluded.name",
            (user_id, name or str(user_id)),
        )


def _log(conn, admin_id, product_id, size, delta, qty_after, note=""):
    return conn.execute(
        "INSERT INTO stock_log (admin_id, product_id, size, delta, qty_after, note) VALUES (?, ?, ?, ?, ?, ?)",
        (admin_id, product_id, size, delta, qty_after, note),
    ).lastrowid


def get_stock(product_id: int):
    """[(size, qty), ...] в порядке, заданном при вводе (S, M, L ...)."""
    with connect() as conn:
        return conn.execute(
            "SELECT size, qty FROM stock WHERE product_id = ? ORDER BY position, size", (product_id,)
        ).fetchall()


def set_stock(product_id: int, sizes, admin_id=None):
    """Полностью заменяет размеры товара списком [(size, qty)]. Пустой список — отключает учёт.
    Каждое изменение количества попадает в журнал (note='set')."""
    with connect() as conn:
        old = dict(conn.execute("SELECT size, qty FROM stock WHERE product_id = ?", (product_id,)).fetchall())
        conn.execute("DELETE FROM stock WHERE product_id = ?", (product_id,))
        new = {}
        for pos, (size, qty) in enumerate(sizes):
            conn.execute(
                "INSERT INTO stock (product_id, size, qty, position) VALUES (?, ?, ?, ?)",
                (product_id, size, qty, pos),
            )
            new[size] = qty
            if qty != old.get(size, 0):
                _log(conn, admin_id, product_id, size, qty - old.get(size, 0), qty, "set")
        for size, qty in old.items():
            if size not in new and qty:
                _log(conn, admin_id, product_id, size, -qty, 0, "set")


def change_stock(product_id: int, size: str, delta: int, admin_id=None):
    """Прибавляет/списывает штуки. Возвращает (статус, остаток, id записи журнала):
    ('ok', 2, 17) · ('no_size', None, None) · ('insufficient', 1, None)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT qty FROM stock WHERE product_id = ? AND size = ?", (product_id, size)
        ).fetchone()
        if row is None:
            return "no_size", None, None
        new_qty = row[0] + delta
        if new_qty < 0:
            return "insufficient", row[0], None
        conn.execute("UPDATE stock SET qty = ? WHERE product_id = ? AND size = ?", (new_qty, product_id, size))
        return "ok", new_qty, _log(conn, admin_id, product_id, size, delta, new_qty)


def get_log_entry(log_id: int):
    """(product_id, size, delta, undone) или None."""
    with connect() as conn:
        return conn.execute(
            "SELECT product_id, size, delta, undone FROM stock_log WHERE id = ?", (log_id,)
        ).fetchone()


def undo_log(log_id: int):
    """Откатывает одну запись журнала. Возвращает (статус, остаток, product_id, size, delta):
    ok / not_found / already / missing (размера уже нет) / conflict (откат дал бы минус)."""
    with connect() as conn:
        entry = conn.execute(
            "SELECT product_id, size, delta, undone FROM stock_log WHERE id = ?", (log_id,)
        ).fetchone()
        if entry is None:
            return "not_found", None, None, None, None
        product_id, size, delta, undone = entry
        if undone:
            return "already", None, product_id, size, delta
        row = conn.execute(
            "SELECT qty FROM stock WHERE product_id = ? AND size = ?", (product_id, size)
        ).fetchone()
        if row is None:
            return "missing", None, product_id, size, delta
        new_qty = row[0] - delta
        if new_qty < 0:
            return "conflict", row[0], product_id, size, delta
        conn.execute("UPDATE stock SET qty = ? WHERE product_id = ? AND size = ?", (new_qty, product_id, size))
        conn.execute("UPDATE stock_log SET undone = 1 WHERE id = ?", (log_id,))
        return "ok", new_qty, product_id, size, delta


def last_log_id(admin_id: int):
    """Последняя не отменённая операция этого админа (установка размеров не считается)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM stock_log WHERE admin_id = ? AND undone = 0 AND note <> 'set' ORDER BY id DESC LIMIT 1",
            (admin_id,),
        ).fetchone()
    return row[0] if row else None


def recent_log(limit: int = 15):
    """[(id, ts, кто, product_id, название, size, delta, qty_after, note, undone), ...] — новые сверху."""
    with connect() as conn:
        return conn.execute(
            '''SELECT l.id, l.ts, COALESCE(a.name, u.first_name, u.username, CAST(l.admin_id AS TEXT), '?'),
                      l.product_id, COALESCE(p.name, 'удалён'), l.size, l.delta, l.qty_after, l.note, l.undone
               FROM stock_log l
               LEFT JOIN admins a ON a.user_id = l.admin_id
               LEFT JOIN users u ON u.user_id = l.admin_id
               LEFT JOIN products p ON p.id = l.product_id
               ORDER BY l.id DESC LIMIT ?''',
            (limit,),
        ).fetchall()


def low_stock(threshold: int = 2, limit: int = 40):
    """[(product_id, название, size, qty), ...] — размеры, где осталось не больше threshold."""
    with connect() as conn:
        return conn.execute(
            '''SELECT p.id, p.name, s.size, s.qty FROM stock s JOIN products p ON p.id = s.product_id
               WHERE s.qty <= ? ORDER BY s.qty, p.name, s.position LIMIT ?''',
            (threshold, limit),
        ).fetchall()


def category_stock(category_id: int):
    """[(product_id, название, [(size, qty), ...]), ...] — у товаров без учёта список пустой."""
    with connect() as conn:
        products = conn.execute(
            "SELECT id, name FROM products WHERE category_id = ? ORDER BY id", (category_id,)
        ).fetchall()
        rows = conn.execute(
            '''SELECT s.product_id, s.size, s.qty FROM stock s JOIN products p ON p.id = s.product_id
               WHERE p.category_id = ? ORDER BY s.product_id, s.position, s.size''',
            (category_id,),
        ).fetchall()
    by_product = {}
    for pid, size, qty in rows:
        by_product.setdefault(pid, []).append((size, qty))
    return [(pid, name, by_product.get(pid, [])) for pid, name in products]


# --- ЛЕНТА КАТАЛОГА (id сообщений, которые нужно будет удалить) ---

def feed_add(chat_id: int, message_ids):
    with connect() as conn:
        conn.executemany(
            "INSERT INTO feed_msgs (chat_id, message_id) VALUES (?, ?)", [(chat_id, mid) for mid in message_ids]
        )


def feed_ids(chat_id: int):
    with connect() as conn:
        return [r[0] for r in conn.execute(
            "SELECT message_id FROM feed_msgs WHERE chat_id = ? ORDER BY rowid", (chat_id,))]


def feed_pop(chat_id: int):
    """Возвращает id сообщений ленты этого чата и забывает их."""
    with connect() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT message_id FROM feed_msgs WHERE chat_id = ? ORDER BY rowid", (chat_id,))]
        conn.execute("DELETE FROM feed_msgs WHERE chat_id = ?", (chat_id,))
    return ids
