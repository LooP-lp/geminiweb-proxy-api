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
                # users 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        email VARCHAR(200) DEFAULT '',
                        is_admin BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                # migrate: add email column if missing
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='users' AND column_name='email'
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN email VARCHAR(200) DEFAULT ''")
                # migrate: add is_admin column if missing
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='users' AND column_name='is_admin'
                """)
                if not cur.fetchone():
                    cur.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT FALSE")
                # first user becomes admin
                cur.execute("UPDATE users SET is_admin = TRUE WHERE id = (SELECT MIN(id) FROM users) AND is_admin = FALSE")
                # api_keys 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS api_keys (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        api_key VARCHAR(52) UNIQUE NOT NULL,
                        note VARCHAR(200) DEFAULT '',
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        last_used_at TIMESTAMP WITH TIME ZONE,
                        is_active BOOLEAN DEFAULT TRUE
                    );
                """)
                # 迁移旧字段大小
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name='api_keys' AND column_name='api_key'
                """)
                if cur.fetchone():
                    cur.execute("ALTER TABLE api_keys ALTER COLUMN api_key TYPE VARCHAR(52)")
                # usage_stats 表
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
                # request_log 表
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
                # user_prompts 表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_prompts (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        type VARCHAR(20) NOT NULL DEFAULT 'prompt',
                        title VARCHAR(200) NOT NULL DEFAULT '',
                        content TEXT NOT NULL DEFAULT '',
                        is_active BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
        except Exception as e:
            print(f"创建表失败: {e}")

    # ============ 用户管理 ============

    def register_user(self, username, password, email=""):
        """注册新用户：对密码进行加盐哈希处理后存储"""
        salt = bcrypt.gensalt()
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), salt)
        try:
            with self.conn.cursor() as cur:
                is_first = cur.execute("SELECT COUNT(*) FROM users")
                count = cur.fetchone()[0]
                is_admin = count == 0
                cur.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin) VALUES (%s, %s, %s, %s)",
                    (username, hashed_password.decode('utf-8'), email, is_admin)
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

    def is_user_admin(self, username):
        """检查用户是否是管理员"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT is_admin FROM users WHERE username = %s", (username,))
                result = cur.fetchone()
                return result and result[0]
        except Exception as e:
            print(f"检查管理员权限失败: {e}")
            return False

    def set_user_admin(self, user_id, is_admin):
        """设置用户管理员权限"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE users SET is_admin = %s WHERE id = %s", (is_admin, user_id))
                return cur.rowcount > 0
        except Exception as e:
            print(f"设置管理员权限失败: {e}")
            return False

    def list_all_users(self):
        """列出所有用户及完整信息"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        u.id, u.username, u.email, u.is_admin, u.created_at,
                        COUNT(DISTINCT k.id) as key_count,
                        COALESCE(SUM(us.request_count), 0) as total_requests,
                        COALESCE(SUM(us.total_tokens), 0) as total_tokens
                    FROM users u
                    LEFT JOIN api_keys k ON k.user_id = u.id
                    LEFT JOIN usage_stats us ON us.user_id = u.id
                    GROUP BY u.id, u.username, u.email, u.is_admin, u.created_at
                    ORDER BY u.id
                """)
                rows = cur.fetchall()
                return [{
                    "id": r[0],
                    "username": r[1],
                    "email": r[2] or "",
                    "is_admin": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                    "key_count": r[5],
                    "total_requests": r[6],
                    "total_tokens": r[7]
                } for r in rows]
        except Exception as e:
            print(f"获取用户列表失败: {e}")
            return []

    def delete_user_data(self, user_id):
        """删除用户及其所有相关数据"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                return cur.rowcount > 0
        except Exception as e:
            print(f"删除用户失败: {e}")
            return False

    # ============ API Key 管理 ============

    @staticmethod
    def _generate_api_key():
        """生成 sk-xxxx 格式的48位随机API Key"""
        chars = string.ascii_letters + string.digits  # 大小写+数字
        random_part = ''.join(random.choices(chars, k=48))
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

    def get_api_keys(self):
        """获取所有有效的 API Key（用于 current-key API）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """SELECT id, user_id, api_key, note, created_at, last_used_at, is_active
                       FROM api_keys WHERE is_active = TRUE ORDER BY last_used_at DESC NULLS LAST"""
                )
                rows = cur.fetchall()
                return [{
                    "id": r[0],
                    "user_id": r[1],
                    "api_key": r[2],
                    "note": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                    "last_used_at": r[5].isoformat() if r[5] else None,
                    "is_active": r[6]
                } for r in rows]
        except Exception as e:
            print(f"获取所有API Key失败: {e}")
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

                cur.execute("""
                    INSERT INTO request_log (user_id, api_key_id, model, prompt_tokens, completion_tokens, total_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, api_key_id, model, prompt_tokens, completion_tokens, total))
        except Exception as e:
            print(f"记录使用统计失败: {e}")

    def record_error(self, user_id, api_key_id, model, error_message):
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
                "today_tokens": 0, "recent_24h_requests": 0, "total_errors": 0,
            }

    def get_hourly_stats_24h(self):
        """获取过去24小时的按小时统计数据（用于折线图）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC') as hour,
                        COUNT(*) as requests,
                        COALESCE(SUM(prompt_tokens), 0) as prompt_tokens,
                        COALESCE(SUM(completion_tokens), 0) as completion_tokens,
                        COALESCE(SUM(total_tokens), 0) as total_tokens
                    FROM request_log
                    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    GROUP BY hour
                    ORDER BY hour
                """)
                rows = cur.fetchall()
            result = []
            for r in rows:
                result.append({
                    "hour": int(r[0]),
                    "requests": int(r[1]),
                    "prompt_tokens": int(r[2]),
                    "completion_tokens": int(r[3]),
                    "total_tokens": int(r[4]),
                })
            return result
        except Exception as e:
            print(f"获取24小时统计失败: {e}")
            return []

    def get_user_hourly_stats_24h(self, user_id):
        """获取某用户过去24小时的按小时统计（按模型分组）"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        EXTRACT(HOUR FROM created_at AT TIME ZONE 'UTC') as hour,
                        model,
                        COUNT(*) as requests,
                        COALESCE(SUM(total_tokens), 0) as total_tokens
                    FROM request_log
                    WHERE user_id = %s AND created_at >= CURRENT_TIMESTAMP - INTERVAL '24 hours'
                    GROUP BY hour, model
                    ORDER BY hour, model
                """, (user_id,))
                rows = cur.fetchall()
            result = []
            for r in rows:
                result.append({
                    "hour": int(r[0]),
                    "model": r[1],
                    "requests": int(r[2]),
                    "total_tokens": int(r[3]),
                })
            return result
        except Exception as e:
            print(f"获取用户24小时统计失败: {e}")
            return []

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

    def get_user_detail(self, user_id):
        """获取用户详细信息：基本信息+API Keys+统计"""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT id, username, email, is_admin, created_at FROM users WHERE id=%s", (user_id,))
                u = cur.fetchone()
                if not u:
                    return None
                result = {
                    "id": u[0], "username": u[1], "email": u[2] or "",
                    "is_admin": u[3],
                    "created_at": u[4].isoformat() if u[4] else None,
                    "api_keys": [], "stats": {},
                }
                cur.execute("SELECT id, api_key, note, is_active, created_at, last_used_at FROM api_keys WHERE user_id=%s ORDER BY id", (user_id,))
                for r in cur.fetchall():
                    result["api_keys"].append({
                        "id": r[0], "api_key": r[1], "note": r[2],
                        "is_active": r[3],
                        "created_at": r[4].isoformat() if r[4] else None,
                        "last_used_at": r[5].isoformat() if r[5] else None,
                    })
                result["stats"] = self.get_user_stats(user_id)
                return result
        except Exception as e:
            print(f"获取用户详情失败: {e}")
            return None

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()

    # ============ 用户 Prompt/Skill 管理 ============

    def list_prompts(self, user_id, ptype='prompt'):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, content, is_active, created_at, updated_at FROM user_prompts WHERE user_id=%s AND type=%s ORDER BY updated_at DESC",
                    (user_id, ptype)
                )
                rows = cur.fetchall()
                return [{"id": r[0], "title": r[1], "content": r[2], "is_active": r[3],
                         "created_at": r[4].isoformat() if r[4] else None,
                         "updated_at": r[5].isoformat() if r[5] else None} for r in rows]
        except Exception as e:
            print(f"获取prompt列表失败: {e}")
            return []

    def create_prompt(self, user_id, ptype, title, content):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO user_prompts (user_id, type, title, content) VALUES (%s, %s, %s, %s) RETURNING id",
                    (user_id, ptype, title, content)
                )
                return cur.fetchone()[0]
        except Exception as e:
            print(f"创建prompt失败: {e}")
            return None

    def update_prompt(self, user_id, prompt_id, title=None, content=None):
        try:
            with self.conn.cursor() as cur:
                sets = []
                vals = []
                if title is not None:
                    sets.append("title = %s")
                    vals.append(title)
                if content is not None:
                    sets.append("content = %s")
                    vals.append(content)
                sets.append("updated_at = CURRENT_TIMESTAMP")
                vals.extend([user_id, prompt_id])
                cur.execute(
                    f"UPDATE user_prompts SET {', '.join(sets)} WHERE user_id=%s AND id=%s",
                    vals
                )
                return cur.rowcount > 0
        except Exception as e:
            print(f"更新prompt失败: {e}")
            return False

    def delete_prompt(self, user_id, prompt_id):
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM user_prompts WHERE user_id=%s AND id=%s", (user_id, prompt_id))
                return cur.rowcount > 0
        except Exception as e:
            print(f"删除prompt失败: {e}")
            return False

    def set_active_prompt(self, user_id, prompt_id, ptype):
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE user_prompts SET is_active=FALSE WHERE user_id=%s AND type=%s", (user_id, ptype))
                if prompt_id and prompt_id > 0:
                    cur.execute("UPDATE user_prompts SET is_active=TRUE WHERE user_id=%s AND id=%s", (user_id, prompt_id))
                return True
        except Exception as e:
            print(f"设置活跃prompt失败: {e}")
            return False

    def get_active_prompt(self, user_id, ptype):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "SELECT id, title, content FROM user_prompts WHERE user_id=%s AND type=%s AND is_active=TRUE",
                    (user_id, ptype)
                )
                r = cur.fetchone()
                if r:
                    return {"id": r[0], "title": r[1], "content": r[2]}
                return None
        except Exception as e:
            print(f"获取活跃prompt失败: {e}")
            return None
