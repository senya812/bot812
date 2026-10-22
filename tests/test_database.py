import os
import sqlite3
import tempfile
import unittest

import database as db


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_path = db.DB_PATH
        db.DB_PATH = os.path.join(self._tmp.name, "test.db")
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old_path
        self._tmp.cleanup()

    def make_product(self, cat_id=None, name="Парка", price=5000):
        if cat_id is None:
            cat_id = db.add_category("Куртки")
        return cat_id, db.add_product(cat_id, name, "тёплая", price, "photo")


class TestUsers(DbTestCase):
    def test_register_and_update(self):
        db.register_user(1, "old", "Аня")
        db.register_user(1, "new", "Анна")
        db.register_user(2, None, None)
        self.assertEqual(sorted(db.get_all_users()), [1, 2])
        with db.connect() as conn:
            row = conn.execute("SELECT username, first_name FROM users WHERE user_id = 1").fetchone()
        self.assertEqual(row, ("new", "Анна"))

    def test_init_is_idempotent(self):
        db.init_db()
        db.init_db()


class TestCatalog(DbTestCase):
    def test_order_and_details(self):
        cid = db.add_category("Обувь")
        a = db.add_product(cid, "A", "d", 1, "p")
        b = db.add_product(cid, "B", "d", 2, "p")
        self.assertEqual([p[0] for p in db.get_products_by_category(cid)], [a, b])
        self.assertEqual(db.get_product_details(a), (cid, "A", "d", 1, "p"))
        self.assertIsNone(db.get_product_details(9999))

    def test_category_lookup(self):
        cid = db.add_category("Шапки")
        self.assertEqual(db.get_category(cid), "Шапки")
        self.assertIsNone(db.get_category(9999))
        self.assertEqual(db.get_category_name(9999), "Неизвестно")

    def test_special_characters_are_stored_as_is(self):
        cid, pid = self.make_product(name="T_shirt *x* [y] <b>")
        self.assertEqual(db.get_product_details(pid)[1], "T_shirt *x* [y] <b>")

    def test_delete_category_cascades_to_products_and_looks(self):
        cid, pid = self.make_product()
        db.add_to_cart(1, pid)
        db.delete_category(cid)
        self.assertEqual(db.get_products_by_category(cid), [])
        self.assertEqual(db.get_cart_items(1), [])
        self.assertEqual(db.get_crm_stats()[2], 0)


class TestLook(DbTestCase):
    def test_add_is_unique_per_user(self):
        _, pid = self.make_product()
        self.assertTrue(db.add_to_cart(1, pid))
        self.assertFalse(db.add_to_cart(1, pid))
        self.assertTrue(db.add_to_cart(2, pid))
        self.assertEqual(db.cart_count(1), 1)
        self.assertTrue(db.is_in_cart(1, pid))

    def test_cannot_add_missing_product(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db.add_to_cart(1, 9999)

    def test_remove_only_touches_own_look(self):
        _, pid = self.make_product()
        db.add_to_cart(1, pid)
        db.add_to_cart(2, pid)
        db.remove_from_cart(1, pid)
        self.assertFalse(db.is_in_cart(1, pid))
        self.assertTrue(db.is_in_cart(2, pid))

    def test_clear_only_touches_own_look(self):
        _, pid = self.make_product()
        db.add_to_cart(1, pid)
        db.add_to_cart(2, pid)
        db.clear_cart(1)
        self.assertEqual(db.cart_count(1), 0)
        self.assertEqual(db.cart_count(2), 1)

    def test_items_have_name_price_and_product_id(self):
        cid, pid = self.make_product(name="Парка", price=5000)
        db.add_to_cart(1, pid)
        (cart_id, name, price, product_id), = db.get_cart_items(1)
        self.assertEqual((name, price, product_id), ("Парка", 5000, pid))

    def test_regression_deleting_product_removes_it_from_looks_and_stats(self):
        """Раньше удалённый товар оставался в cart и завышал статистику «клиентов с корзиной»."""
        _, pid = self.make_product()
        db.add_to_cart(1, pid)
        db.delete_product(pid)
        self.assertEqual(db.get_cart_items(1), [])
        self.assertEqual(db.cart_count(1), 0)
        self.assertEqual(db.get_crm_stats(), (0, 0, 0))


class TestFeed(DbTestCase):
    def test_add_ids_pop_and_isolation_between_chats(self):
        db.feed_add(1, [10, 11, 12]); db.feed_add(2, [20])
        self.assertEqual(db.feed_ids(1), [10, 11, 12])
        self.assertEqual(db.feed_pop(1), [10, 11, 12])
        self.assertEqual(db.feed_ids(1), []); self.assertEqual(db.feed_ids(2), [20])
        self.assertEqual(db.feed_pop(1), [])

    def test_order_is_preserved_across_several_additions(self):
        db.feed_add(1, [5, 3]); db.feed_add(1, [9, 4])
        self.assertEqual(db.feed_ids(1), [5, 3, 9, 4])

    def test_init_drops_records_older_than_two_days(self):
        db.feed_add(1, [1, 2])
        with db.connect() as conn:
            conn.execute("UPDATE feed_msgs SET ts = datetime('now', '-3 days') WHERE message_id = 1")
        db.init_db()
        self.assertEqual(db.feed_ids(1), [2])


class TestStock(DbTestCase):
    def setUp(self):
        super().setUp()
        self.cid, self.pid = self.make_product()

    def test_set_and_get_keep_input_order(self):
        db.set_stock(self.pid, [("M", 3), ("S", 2), ("XL", 0)], admin_id=1)
        self.assertEqual(db.get_stock(self.pid), [("M", 3), ("S", 2), ("XL", 0)])

    def test_product_without_stock_rows_has_no_sizes(self):
        self.assertEqual(db.get_stock(self.pid), [])

    def test_set_replaces_previous_list(self):
        db.set_stock(self.pid, [("S", 2), ("M", 3)], 1)
        db.set_stock(self.pid, [("L", 1)], 1)
        self.assertEqual(db.get_stock(self.pid), [("L", 1)])
        db.set_stock(self.pid, [], 1)  # пустой список — учёт выключен
        self.assertEqual(db.get_stock(self.pid), [])

    def test_set_logs_only_real_changes(self):
        db.set_stock(self.pid, [("S", 2), ("M", 3)], 1)
        db.set_stock(self.pid, [("S", 2), ("M", 5)], 1)   # изменился только M (+2)
        rows = db.recent_log(10)
        self.assertEqual([(r[5], r[6], r[8]) for r in rows[:1]], [("M", 2, "set")])
        self.assertEqual(len(rows), 3)

    def test_change_ok_no_size_and_insufficient(self):
        db.set_stock(self.pid, [("S", 2)], 1)
        status, qty, log_id = db.change_stock(self.pid, "S", -1, 1)
        self.assertEqual((status, qty), ("ok", 1)); self.assertIsNotNone(log_id)
        self.assertEqual(db.change_stock(self.pid, "XL", -1, 1), ("no_size", None, None))
        self.assertEqual(db.change_stock(self.pid, "S", -5, 1), ("insufficient", 1, None))
        self.assertEqual(db.get_stock(self.pid), [("S", 1)])   # неудачные операции ничего не меняют
        self.assertEqual(db.change_stock(self.pid, "S", +4, 1)[:2], ("ok", 5))

    def test_stock_cannot_go_negative_at_db_level(self):
        db.set_stock(self.pid, [("S", 1)], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connect() as conn:
                conn.execute("UPDATE stock SET qty = -1 WHERE product_id = ?", (self.pid,))

    def test_undo_restores_and_is_single_use(self):
        db.set_stock(self.pid, [("M", 3)], 1)
        _, _, log_id = db.change_stock(self.pid, "M", -2, 1)
        self.assertEqual(db.undo_log(log_id)[:2], ("ok", 3))
        self.assertEqual(db.get_stock(self.pid), [("M", 3)])
        self.assertEqual(db.undo_log(log_id)[0], "already")
        self.assertEqual(db.undo_log(9999)[0], "not_found")

    def test_undo_refuses_when_it_would_go_negative(self):
        db.set_stock(self.pid, [("M", 3)], 1)
        _, _, added = db.change_stock(self.pid, "M", +2, 1)      # 5
        db.change_stock(self.pid, "M", -5, 2)                     # другой админ продал всё: 0
        self.assertEqual(db.undo_log(added)[:2], ("conflict", 0))
        self.assertEqual(db.get_stock(self.pid), [("M", 0)])

    def test_undo_when_size_was_removed(self):
        db.set_stock(self.pid, [("M", 3)], 1)
        _, _, log_id = db.change_stock(self.pid, "M", -1, 1)
        db.set_stock(self.pid, [("L", 1)], 1)
        self.assertEqual(db.undo_log(log_id)[0], "missing")

    def test_last_log_id_is_per_admin_and_skips_set_and_undone(self):
        db.set_stock(self.pid, [("M", 5)], 1)
        self.assertIsNone(db.last_log_id(1))                       # «установка» не отменяется «последним»
        _, _, a = db.change_stock(self.pid, "M", -1, 1)
        _, _, b = db.change_stock(self.pid, "M", -1, 2)
        self.assertEqual(db.last_log_id(1), a); self.assertEqual(db.last_log_id(2), b)
        db.undo_log(a)
        self.assertIsNone(db.last_log_id(1))

    def test_journal_shows_names_and_survives_product_deletion(self):
        db.register_user(1, "anna", "Анна")
        db.set_stock(self.pid, [("M", 3)], 1)
        db.change_stock(self.pid, "M", -1, 1)
        row = db.recent_log(1)[0]
        self.assertEqual((row[2], row[3], row[4], row[5], row[6], row[7]), ("Анна", self.pid, "Парка", "M", -1, 2))
        db.delete_product(self.pid)
        self.assertEqual(db.recent_log(1)[0][4], "удалён")
        self.assertEqual(db.get_stock(self.pid), [])               # размеры удалились каскадом

    def test_journal_uses_remembered_admin_name_even_without_start(self):
        db.touch_admin(5, "Борис")
        db.touch_admin(5, "Борис Иванов")   # имя обновляется
        db.set_stock(self.pid, [("M", 3)], 5)
        self.assertEqual(db.recent_log(1)[0][2], "Борис Иванов")
        db.change_stock(self.pid, "M", -1, 99)                      # админ без имени — виден хотя бы id
        self.assertEqual(db.recent_log(1)[0][2], "99")

    def test_low_stock_and_category_stock(self):
        other = db.add_product(self.cid, "Шарф", "d", 1, "p")
        db.add_product(self.cid, "Без учёта", "d", 1, "p")
        db.set_stock(self.pid, [("S", 0), ("M", 2), ("L", 9)], 1)
        db.set_stock(other, [("ONE", 1)], 1)
        low = db.low_stock(2)
        self.assertEqual([(r[1], r[2], r[3]) for r in low], [("Парка", "S", 0), ("Шарф", "ONE", 1), ("Парка", "M", 2)])
        items = db.category_stock(self.cid)
        self.assertEqual([i[1] for i in items], ["Парка", "Шарф", "Без учёта"])
        self.assertEqual(items[0][2], [("S", 0), ("M", 2), ("L", 9)]); self.assertEqual(items[2][2], [])

    def test_stock_for_missing_product_is_rejected(self):
        with self.assertRaises(sqlite3.IntegrityError):
            db.set_stock(9999, [("S", 1)], 1)


class TestMigration(unittest.TestCase):
    """Старая база из первой версии бота: дубли в cart и записи без товара."""

    def test_legacy_database_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path, db.DB_PATH = db.DB_PATH, os.path.join(tmp, "legacy.db")
            try:
                conn = sqlite3.connect(db.DB_PATH)
                conn.executescript('''
                    CREATE TABLE users (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                                        registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL);
                    CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, category_id INTEGER,
                        name TEXT NOT NULL, description TEXT, price INTEGER, photo_id TEXT,
                        FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE);
                    CREATE TABLE cart (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                        product_id INTEGER NOT NULL,
                        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE);
                    INSERT INTO categories (name) VALUES ('Куртки');
                    INSERT INTO products (category_id, name, description, price, photo_id)
                        VALUES (1, 'Парка', 'd', 5000, 'p');
                    INSERT INTO cart (user_id, product_id) VALUES (1, 1), (1, 1), (1, 777);
                ''')
                conn.commit()
                conn.close()

                db.init_db()

                self.assertEqual(db.cart_count(1), 1)
                self.assertEqual(len(db.get_cart_items(1)), 1)
                self.assertFalse(db.add_to_cart(1, 1))  # дубль теперь невозможен
            finally:
                db.DB_PATH = old_path


if __name__ == "__main__":
    unittest.main()
