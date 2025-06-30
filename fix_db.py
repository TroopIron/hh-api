# fix_db.py  ── однократная миграция
import sqlite3, os
db = "tg_users.db"
if not os.path.exists(db):
    print("Файл базы не найден:", db); quit()

con = sqlite3.connect(db)
con.execute("""
    CREATE TABLE IF NOT EXISTS user_settings(
        tg_user INTEGER NOT NULL,
        field   TEXT    NOT NULL,
        value   TEXT,
        PRIMARY KEY (tg_user, field)
    );
""")
con.commit()
con.close()
print("✅  user_settings есть, можно запускать бот")