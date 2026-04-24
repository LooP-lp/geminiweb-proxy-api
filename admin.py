from db_manager import DBManager
import sys

def list_users():
    print("=" * 80)
    print("  用户列表")
    print("=" * 80)
    print()
    
    try:
        db = DBManager()
        users = db.list_all_users()
        
        if not users:
            print("暂无用户数据")
            return
        
        print(f"{'ID':<5} {'用户名':<18} {'API Keys':<10} {'请求数':<12} {'Token用量':<15} {'创建时间':<20}")
        print("-" * 80)
        for u in users:
            tokens = _format_tokens(u['total_tokens'])
            print(f"{u['id']:<5} {u['username']:<18} {u['key_count']:<10} {u['total_requests']:<12} {tokens:<15} {u['created_at'][:19]:<20}")
        print()
        print(f"共 {len(users)} 个用户")
        
    except Exception as e:
        print(f"❌ 获取用户列表失败: {e}")
        sys.exit(1)

def _format_tokens(n):
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.2f}B"
    elif n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    elif n >= 1_000:
        return f"{n/1_000:.2f}K"
    return str(n)

def delete_user():
    print("=" * 50)
    print("  删除用户数据")
    print("=" * 50)
    print()
    
    try:
        db = DBManager()
        users = db.list_all_users()
        
        if not users:
            print("暂无用户数据")
            return
        
        print(f"{'ID':<6} {'用户名':<20} {'创建时间':<20}")
        print("-" * 50)
        for u in users:
            print(f"{u['id']:<6} {u['username']:<20} {u['created_at'][:19]:<20}")
        print()
        
        user_id = input("请输入要删除的用户ID: ").strip()
        if not user_id.isdigit():
            print("错误: 请输入有效的数字ID")
            sys.exit(1)
        
        user_id = int(user_id)
        user = next((u for u in users if u['id'] == user_id), None)
        if not user:
            print(f"错误: 用户ID {user_id} 不存在")
            sys.exit(1)
        
        confirm = input(f"确认删除用户 [{user['username']}] 的所有数据？(yes/no): ").strip().lower()
        if confirm != 'yes':
            print("已取消")
            return
        
        if db.delete_user_data(user_id):
            print(f"✅ 用户 [{user['username']}] 数据已删除")
        else:
            print("❌ 删除失败")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ 操作失败: {e}")
        sys.exit(1)

def create_user():
    print("=" * 50)
    print("  创建管理员账号")
    print("=" * 50)
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
            print(f"✅ 成功！账号 [{username}] 已创建")
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

def main():
    print()
    print("=" * 50)
    print("  PostgreSQL 管理工具")
    print("=" * 50)
    print()
    print("1. 查看用户列表")
    print("2. 创建管理员账号")
    print("3. 删除用户数据")
    print("0. 退出")
    print()
    
    choice = input("请选择操作: ").strip()
    
    if choice == '1':
        list_users()
    elif choice == '2':
        create_user()
    elif choice == '3':
        delete_user()
    elif choice == '0' or choice == '':
        print("已退出")
    else:
        print("无效选择")
        sys.exit(1)

if __name__ == "__main__":
    main()