import sys
from pathlib import Path

from sqlalchemy import text

backend_root = Path(__file__).resolve().parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from app.core.db import SessionLocal  # Updated to match your exact path # Adjust this import if your session maker is named differently

def clear_database():
    print("--- STARTING DATABASE CLEANUP ---")
    db = SessionLocal()
    
    try:
        # 1. Break the Foreign Key constraint by nullifying the selected routes
        print("Unlinking selected routes...")
        db.execute(text("UPDATE trips SET selected_route_id = NULL;"))
        
        # 2. Delete the rows in order
        print("Deleting routes...")
        db.execute(text("DELETE FROM routes;"))
        
        print("Deleting POIs...")
        db.execute(text("DELETE FROM pois;"))
        
        print("Deleting trips...")
        db.execute(text("DELETE FROM trips;"))
        
        # 3. Lock in the changes
        db.commit()
        print("--- DATABASE CLEARED SUCCESSFULLY ---")
        
    except Exception as e:
        db.rollback()
        print(f"FAILED: An error occurred: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    clear_database()