from db_manager import DBManager
import sys

def main():
    print("=" * 40)
    print("  PostgreSQL 管理员账号创建工具")
    print("=" * 40)
    print()

    username = input("请输入用户名: ").strip()
    if not username:
        print("错误: 用户名不能为空")
        sys.exit(1)

    password = input("请输入密码: ").strip()
    if not password:
        print("错误: 密码不能为空")
        sys.exit(1)

    confirm_password = input("请再次输入密码: ").strip()
    if password != confirm_password:
        print("错误: 两次输入的密码不一致")
        sys.exit(1)

    print()
    print(f"正在创建用户: {username} ...")

    try:
        db = DBManager()
        if db.register_user(username, password):
            print("-" * 40)
            print(f"✅ 成功！账号 [{username}] 已存入 PostgreSQL")
            print(f"   数据库: user_system (端口 6701)")
            print("-" * 40)
        else:
            print(f"❌ 失败: 用户 [{username}] 已存在")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 连接数据库失败: {e}")
        print()
        print("请确保 PostgreSQL 已启动，并执行以下 SQL 初始化数据库:")
        print("-" * 40)
        print("CREATE DATABASE user_system;")
        print("\\c user_system;")
        print("CREATE TABLE users (")
        print("    id SERIAL PRIMARY KEY,")
        print("    username VARCHAR(50) UNIQUE NOT NULL,")
        print("    password_hash TEXT NOT NULL,")
        print("    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP")
        print(");")
        print("-" * 40)
        sys.exit(1)

if __name__ == "__main__":
    main()