import os
import psycopg2
import bcrypt
from dotenv import load_dotenv

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
        except Exception as e:
            print(f"数据库连接失败: {e}")
            raise

    def register_user(self, username, password):
        """
        注册新用户：对密码进行加盐哈希处理后存储
        """
        # 生成盐并哈希密码
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
        """
        验证用户登录：比对输入密码与数据库中的哈希值
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users WHERE username = %s", (username,))
                result = cur.fetchone()

                if result:
                    stored_hash = result[0].encode('utf-8')
                    # 验证密码
                    if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
                        return True
            return False
        except Exception as e:
            print(f"验证过程中出错: {e}")
            return False

    def __del__(self):
        if hasattr(self, 'conn'):
            self.conn.close()