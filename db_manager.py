import os
import string
import random
import psycopg2
import bcrypt
from dotenv import load_dotenv
from datetime import datetime

# 加载环境变量
load_dotenv()


class DBManager:
    def __init__(self):
        try:
            self.conn = psycopg2.connect(
                dbname=os.getenv("DB_NAME", "user_system"),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD", "LiaoPeng6"),
                host=os.getenv("DB_HOST", "127.0.0.1"),
                port=os.getenv("DB_PORT", "6701")
            )
            self.conn.autocommit = True
            self._ensure_tables()
        except Exception as e:
            print(f"数据库连接失败: {e}")
            raise

    def _ensure_tables(self):
        """确保所有必要的表都已创建"""
        try:
            with self.conn.cursor() as cur:
                # api_keys 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        api_key VARCHAR(32) UNIQUE NOT NULL,
                        note VARCHAR(200) DEFAULT '',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TIMESTAMP WITH TIME ZONE,
                        is_active BOOLEAN DEFAULT TRUE
                    );
                """)
                # usage_stats 表 (按用户+模型维度聚合)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS usage_stats (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
                        model VARCHAR(100) NOT NULL DEFAULT 'unknown',
                        request_count INTEGER DEFAULT 0,
                        prompt_tokens BIGINT DEFAULT 0,
                        completion_tokens BIGINT DEFAULT 0,
                        total_tokens BIGINT DEFAULT 0,
                        date DATE DEFAULT CURRENT_DATE,
                        UNIQUE(user_id, api_key_id, model, date)
                    );
                """)
                # request_log 表 (详细请求日志)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS request_log (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
                        model VARCHAR(100),
                        prompt_tokens INTEGER DEFAULT 0,
                        completion_tokens INTEGER DEFAULT 0,
                        total_tokens INTEGER DEFAULT 0,
                        status VARCHAR(20) DEFAULT 'success',
                        error_message TEXT,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        except Exception as e:
            print(f"创建表失败: {e}")

    # ============ 用户管理 ============

    def register_user(self, username, password):
        """注册新用户：对密码进行加盐哈希处理后存储"""
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, hashed_password.decode('utf-8'))
                )
            return True
        except psycopg2.IntegrityError:
            print(f"用户 {username} 已存在")
            return False
        except Exception as e:
            print(f"注册失败: {e}")
            return False

    def authenticate_user(self, username, password):
        """验证用户登录：比对输入密码与数据库中的哈希值"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
                result = cur.fetchone()
                if result:
                    stored_hash = result[0].encode('utf-8')
                    if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                        return True
            return False
        except Exception as e:
            print(f"验证过程中出错: {e}")
            return False

    def get_user_id(self, username):
        """根据用户名获取用户ID"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE username = %s", (username,))
                result = cur.fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"获取用户ID失败: {e}")
            return None

    # ============ API Key 管理 ============

    @staticmethod
    def _generate_api_key():
        """生成 sk-xxxx 格式的16位随机API Key"""
        chars = string.ascii_letters + string.digits  # 大小写+数字
        random_part = ''.join(random.choices(chars, k=16))
        return f"sk-{random_part}"

    def create_api_key(self, user_id, note=""):
        """为用户创建新的API Key"""
        api_key = self._generate_api_key()
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO api_keys (user_id, api_key, note) VALUES (%s, %s, %s) RETURNING id, api_key, created_at",
                    (user_id, api_key, note[:200])
                )
                row = cur.fetchone()
                return {
                    "id": row[0],
                    "api_key": row[1],
                    "note": note[:200],
                    "created_at": row[2].isoformat() if row[2] else None
                }
        except Exception as e:
            print(f"创建API Key失败: {e}")
            return None

    def list_api_keys(self, user_id):
        """列出用户所有API Key"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT id, api_key, note, created_at, last_used_at, is_active
                       FROM api_keys WHERE user_id = %s ORDER BY created_at DESC""",
                    (user_id,)
                )
                rows = cur.fetchall()
                return [{
                    "id": r[0],
                    "api_key": r[1],
                    "note": r[2],
                    "created_at": r[3].isoformat() if r[3] else None,
                    "last_used_at": r[4].isoformat() if r[4] else None,
                    "is_active": r[5]
                } for r in rows]
        except Exception as e:
            print(f"查询API Key失败: {e}")
            return []

    def delete_api_key(self, user_id, key_id):
        """删除用户的指定API Key"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM api_keys WHERE id = %s AND user_id = %s",
                    (key_id, user_id)
                )
                return cur.rowcount > 0
        except Exception as e:
            print(f"删除API Key失败: {e}")
            return False

    def toggle_api_key(self, user_id, key_id):
        """启用/禁用API Key"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "UPDATE api_keys SET is_active = NOT is_active WHERE id = %s AND user_id = %s RETURNING is_active",
                    (key_id, user_id)
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            print(f"切换API Key状态失败: {e}")
            return None

    def verify_api_key_db(self, api_key):
        """
        验证API Key是否有效，返回 (user_id, key_id) 或 None
        同时更新 last_used_at
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT ak.id, ak.user_id FROM api_keys ak
                       WHERE ak.api_key = %s AND ak.is_active = TRUE""",
                    (api_key,)
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE api_keys SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s",
                        (row[0],)
                    )
                    return {"key_id": row[0], "user_id": row[1]}
                return None
        except Exception as e:
            print(f"验证API Key失败: {e}")
            return None

    # ============ 使用统计 ============

    def record_usage(self, user_id, api_key_id, model, prompt_tokens, completion_tokens):
        """记录一次API调用的token使用量"""
        total = prompt_tokens + completion_tokens
        try:
            with self.conn.cursor() as cur:
                # 更新聚合统计 (upsert)
                cur.execute("""
                    INSERT INTO usage_stats (user_id, api_key_id, model, request_count, prompt_tokens, completion_tokens, total_tokens, date)
                    VALUES (%s, %s, %s, 1, %s, %s, %s, CURRENT_DATE)
                    ON CONFLICT (user_id, api_key_id, model, date)
                    DO UPDATE SET
                        request_count = usage_stats.request_count + 1,
                        prompt_tokens = usage_stats.prompt_tokens + EXCLUDED.prompt_tokens,
                        completion_tokens = usage_stats.completion_tokens + EXCLUDED.completion_tokens,
                        total_tokens = usage_stats.total_tokens + EXCLUDED.total_tokens
                """, (user_id, api_key_id, model, prompt_tokens, completion_tokens, total))

                # 插入详细日志
                cur.execute("""
                    INSERT INTO request_log (user_id, api_key_id, model, prompt_tokens, completion_tokens, total_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, api_key_id, model, prompt_tokens, completion_tokens, total))
        except Exception as e:
            print(f"记录使用统计失败: {e}")

    def record_error(self, user_id, api_key_id, model, error_message):
        """记录一次失败的API调用"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO request_log (user_id, api_key_id, model, status, error_message)
                    VALUES (%s, %s, %s, 'error', %s)
                """, (user_id, api_key_id, model, str(error_message)[:500]))
        except Exception as e:
            print(f"记录错误日志失败: {e}")

    def get_global_stats(self):
        """获取全局统计数据"""
        try:
            with self.conn.cursor() as cur:
                # 总计
                cur.execute("""
                    SELECT COALESCE(SUM(request_count),0),
                           COALESCE(SUM(prompt_tokens),0),
                           COALESCE(SUM(completion_tokens),0),
                           COALESCE(SUM(total_tokens),0)
                    FROM usage_stats
                """)
                total = cur.fetchone()

                # 按模型分组
                cur.execute("""
                    SELECT model, SUM(request_count) as reqs
                    FROM usage_stats
                    GROUP BY model ORDER BY reqs DESC
                """)
                by_model = {r[0]: int(r[1]) for r in cur.fetchall()}

                # 今日统计
                cur.execute("""
                    SELECT COALESCE(SUM(request_count),0),
                           COALESCE(SUM(total_tokens),0)
                    FROM usage_stats WHERE date = CURRENT_DATE
                """)
                today = cur.fetchone()

                # 最近24小时请求数
                cur.execute("""
                    SELECT COUNT(*) FROM request_log
                    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                """)
                recent_24h = cur.fetchone()[0]

                # 错误次数
                cur.execute("""
                    SELECT COUNT(*) FROM request_log WHERE status = 'error'
                """)
                error_count = cur.fetchone()[0]

                return {
                    "total_requests": int(total[0]),
                    "total_prompt_tokens": int(total[1]),
                    "total_completion_tokens": int(total[2]),
                    "total_tokens": int(total[3]),
                    "requests_by_model": by_model,
                    "today_requests": int(today[0]),
                    "today_tokens": int(today[1]),
                    "recent_24h_requests": int(recent_24h),
                    "total_errors": int(error_count),
                }
        except Exception as e:
            print(f"获取统计失败: {e}")
            return {
                "total_requests": 0, "total_prompt_tokens": 0,
                "total_completion_tokens": 0, "total_tokens": 0,
                "requests_by_model": {}, "today_requests": 0,
                "today_tokens": 0, "recent_24h_requests": 0,
                "total_errors": 0,
            }

    def get_user_stats(self, user_id):
        """获取某用户的统计数据"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT COALESCE(SUM(request_count),0),
                           COALESCE(SUM(prompt_tokens),0),
                           COALESCE(SUM(completion_tokens),0),
                           COALESCE(SUM(total_tokens),0)
                    FROM usage_stats WHERE user_id = %s
                """, (user_id,))
                total = cur.fetchone()

                cur.execute("""
                    SELECT model, SUM(request_count) as reqs
                    FROM usage_stats WHERE user_id = %s
                    GROUP BY model ORDER BY reqs DESC
                """, (user_id,))
                by_model = {r[0]: int(r[1]) for r in cur.fetchall()}

                return {
                    "total_requests": int(total[0]),
                    "total_prompt_tokens": int(total[1]),
                    "total_completion_tokens": int(total[2]),
                    "total_tokens": int(total[3]),
                    "requests_by_model": by_model,
                }
        except Exception as e:
            print(f"获取用户统计失败: {e}")
            return {
                "total_requests": 0, "total_prompt_tokens": 0,
                "total_completion_tokens": 0, "total_tokens": 0,
                "requests_by_model": {},
            }

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()
