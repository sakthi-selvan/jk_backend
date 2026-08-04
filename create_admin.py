"""Create default admin user"""
from app.db.database import SessionLocal
from app.models.admin import Admin
from app.core.security import get_password_hash

def create_admin():
    db = SessionLocal()
    try:
        # Check if admin exists
        admin = db.query(Admin).filter(Admin.username == "admin").first()
        if admin:
            print("Admin already exists")
            return

        # Create admin
        new_admin = Admin(
            username="admin",
            email="admin@jktaxi.com",
            password_hash=get_password_hash("admin123"),
            is_active=True
        )
        db.add(new_admin)
        db.commit()
        print("✅ Admin created successfully!")
        print("Username: admin")
        print("Password: admin123")
    finally:
        db.close()

if __name__ == "__main__":
    create_admin()
