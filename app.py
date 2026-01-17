import os
import json
import threading
import tempfile
import shutil
import functools
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# ==========================================
# 1. CONFIGURATION & SETUP
# ==========================================
load_dotenv()

# Configure Logging (Essential for production debugging)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Security: Session & Cookie Hardening
app.secret_key = os.getenv("SECRET_KEY", "DEV_SECRET_KEY_982374_CHANGE_IN_PROD")
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# app.config['SESSION_COOKIE_SECURE'] = True  # Uncomment when using HTTPS

# Paths
BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, 'data')

# File References
FILES = {
    'users': os.path.join(DATA_DIR, 'users.json'),
    'fresh': os.path.join(DATA_DIR, 'fresh_inventory.json'),
    'expired': os.path.join(DATA_DIR, 'expired_inventory.json'),
    'categories': os.path.join(DATA_DIR, 'categories.json')
}

# Immutable System Categories
DEFAULT_CATEGORIES = [
    {"name": "General", "type": "system"},
    {"name": "Food", "type": "system"},
    {"name": "Medicine", "type": "system"},
    {"name": "Documents", "type": "system"},
    {"name": "Personal Care", "type": "system"}
]

# Thread Safety Lock
DB_LOCK = threading.RLock()

# ==========================================
# 2. ROBUST DATA ACCESS LAYER (DAL)
# ==========================================
class DataManager:
    """
    Handles file operations with Atomic Writes and Corruption Prevention.
    """
    
    @staticmethod
    def ensure_directory():
        """Bootstraps data storage safely."""
        try:
            if not os.path.exists(DATA_DIR):
                os.makedirs(DATA_DIR)
            
            for key, path in FILES.items():
                if not os.path.exists(path):
                    initial_data = {} if key == 'users' else []
                    
                    # Seed Categories
                    if key == 'categories':
                        initial_data = [
                            {
                                "id": f"sys_{idx}",
                                "name": cat["name"],
                                "type": "system",
                                "owner": "system"
                            } for idx, cat in enumerate(DEFAULT_CATEGORIES)
                        ]
                    DataManager.save(path, initial_data)
        except Exception as e:
            logger.critical(f"Failed to initialize data directory: {e}")
            raise

    @staticmethod
    def load(filepath: str) -> Any:
        """Reads JSON safely, returning empty structures on failure."""
        if not os.path.exists(filepath):
            return {} if 'users.json' in filepath else []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Corrupt file {filepath}: {e}")
            return {} if 'users.json' in filepath else []

    @staticmethod
    def save(filepath: str, data: Any) -> None:
        """
        Atomic Write Strategy:
        1. Write to temp file.
        2. Flush and sync.
        3. Atomic rename (replace) original file.
        This prevents data loss on power failure/crash.
        """
        dir_name = os.path.dirname(filepath)
        # Create temp file in same filesystem
        try:
            with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tmp_file:
                json.dump(data, tmp_file, indent=4)
                temp_name = tmp_file.name
                tmp_file.flush()
                os.fsync(tmp_file.fileno()) # Force write to disk

            # Atomic swap
            shutil.move(temp_name, filepath)
        except Exception as e:
            if 'temp_name' in locals() and os.path.exists(temp_name):
                os.remove(temp_name)
            logger.critical(f"Failed to save {filepath}: {e}")
            raise e

# ==========================================
# 3. SERVICE LAYER (Business Logic)
# ==========================================
class InventoryService:
    
    @staticmethod
    def get_inventory(username: str) -> Dict[str, List]:
        """
        Pipeline: Load -> Check Expiry -> Purge Old -> Return User Data.
        Self-healing: Corrupt dates are automatically cleaned up.
        """
        with DB_LOCK:
            all_fresh = DataManager.load(FILES['fresh'])
            all_expired = DataManager.load(FILES['expired'])
            
            today_str = datetime.now().strftime('%Y-%m-%d')
            today_date = datetime.now()
            
            updates_needed = False
            new_fresh = []
            
            # --- Pipeline 1: Fresh -> Expired ---
            for item in all_fresh:
                # 1. Self-Heal: Missing Category
                if 'category' not in item:
                    item['category'] = 'General'
                    updates_needed = True

                # 2. Check Expiry (Robustly)
                try:
                    is_expired = False
                    if item.get('expiry_date'):
                        # String comparison is fast for ISO format YYYY-MM-DD
                        if item['expiry_date'] < today_str:
                            is_expired = True
                    
                    if is_expired:
                        item['archived_at'] = today_str
                        all_expired.append(item)
                        updates_needed = True
                    else:
                        new_fresh.append(item)
                except Exception:
                    # If date logic fails (bad data), keep it safe in fresh to prevent data loss
                    new_fresh.append(item)
            
            # --- Pipeline 2: Purge Old Expired (> 30 Days) ---
            final_expired = []
            for item in all_expired:
                # Self-Heal
                if 'category' not in item:
                    item['category'] = 'General'
                    updates_needed = True
                
                try:
                    # Parse date strictly for purging math
                    exp_date = datetime.strptime(item['expiry_date'], '%Y-%m-%d')
                    if today_date < (exp_date + timedelta(days=30)):
                        final_expired.append(item)
                    else:
                        updates_needed = True # Purged
                except (ValueError, TypeError):
                    # Corrupt date data in expired list -> Purge it to clean DB
                    updates_needed = True 

            # --- Atomic Save ---
            if updates_needed:
                DataManager.save(FILES['fresh'], new_fresh)
                DataManager.save(FILES['expired'], final_expired)
            
            # Filter for current user
            return {
                "fresh": [i for i in new_fresh if i.get('owner') == username],
                "expired": [i for i in final_expired if i.get('owner') == username]
            }

    @staticmethod
    def add_item(data: dict, username: str) -> dict:
        # Generate High-Resolution ID to prevent collision
        item_id = int(datetime.now().timestamp() * 1_000_000)
        
        item = {
            "id": item_id,
            "name": data['name'],
            "expiry_date": data['expiry_date'],
            "category": data.get('category', 'General'),
            "owner": username,
            "added_at": datetime.now().strftime('%Y-%m-%d')
        }
        
        with DB_LOCK:
            fresh = DataManager.load(FILES['fresh'])
            fresh.append(item)
            DataManager.save(FILES['fresh'], fresh)
        return item

    @staticmethod
    def delete_item(item_id: int, username: str) -> bool:
        with DB_LOCK:
            fresh = DataManager.load(FILES['fresh'])
            
            # Filter: Keep item if (ID mismatch) OR (Owner mismatch)
            # This prevents User A from deleting User B's item even if they guess the ID
            new_fresh = [i for i in fresh if not (i['id'] == item_id and i['owner'] == username)]
            
            if len(new_fresh) != len(fresh):
                DataManager.save(FILES['fresh'], new_fresh)
                return True
            return False

class CategoryService:
    
    @staticmethod
    def get_categories(username: str) -> List[dict]:
        all_cats = DataManager.load(FILES['categories'])
        
        # Priority Map: System Defaults overwrite Custom duplicates if any exist
        cat_map = {c['name']: c for c in DEFAULT_CATEGORIES}
        
        for c in all_cats:
            if c.get('owner') == username:
                # Only add custom category if name doesn't conflict with system
                if c['name'] not in cat_map:
                    cat_map[c['name']] = c
        
        return sorted(list(cat_map.values()), key=lambda x: x['name'])

    @staticmethod
    def add_category(name: str, username: str) -> Tuple[bool, Any]:
        with DB_LOCK:
            all_cats = DataManager.load(FILES['categories'])
            
            # Duplicate Check (Case Insensitive)
            name_lower = name.lower()
            for c in all_cats:
                # Check System types
                if c.get('type') == 'system' and c['name'].lower() == name_lower:
                    return False, "Category already exists (System)"
                # Check User types
                if c.get('owner') == username and c['name'].lower() == name_lower:
                    return False, "Category already exists"
            
            new_cat = {
                "id": int(datetime.now().timestamp() * 1_000_000),
                "name": name,
                "type": "custom",
                "owner": username
            }
            all_cats.append(new_cat)
            DataManager.save(FILES['categories'], all_cats)
            return True, new_cat

    @staticmethod
    def delete_category(name: str, username: str) -> Tuple[bool, str]:
        with DB_LOCK:
            all_cats = DataManager.load(FILES['categories'])
            
            # Find category to delete (Must be Custom AND Owned by user)
            cat_to_del = None
            for c in all_cats:
                if c['name'] == name and c.get('owner') == username and c.get('type') == 'custom':
                    cat_to_del = c
                    break
            
            if not cat_to_del:
                return False, "Category not found or permission denied."

            # 1. Delete Category
            all_cats = [c for c in all_cats if c['id'] != cat_to_del['id']]
            DataManager.save(FILES['categories'], all_cats)
            
            # 2. Migrate Inventory (Orphan Prevention)
            # Function to migrate a list of items
            def migrate_items(file_key):
                items = DataManager.load(FILES[file_key])
                dirty = False
                for item in items:
                    if item.get('owner') == username and item.get('category') == name:
                        item['category'] = 'General'
                        dirty = True
                if dirty:
                    DataManager.save(FILES[file_key], items)

            migrate_items('fresh')
            migrate_items('expired')

            return True, "Success"

# ==========================================
# 4. HELPERS & DECORATORS
# ==========================================

def login_required_api(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_valid_json():
    """
    Robust JSON parser that handles edge cases where request.json might be None
    or the Content-Type header is missing.
    """
    try:
        data = request.get_json(force=True, silent=True)
        return data if data is not None else {}
    except Exception:
        return {}

# ==========================================
# 5. ROUTES (CONTROLLERS)
# ==========================================


# Ensure data directory and seed files exist immediately (compatible with older Flask)
try:
    DataManager.ensure_directory()
except Exception as e:
    logger.critical(f"Failed to initialize storage at import time: {e}")
    raise



@app.route('/')
def index():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('index.html', user=session['user'])

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        if 'user' in session: return redirect(url_for('index'))
        return render_template('login.html', mode="login")
        
    username = request.form.get('username')
    password = request.form.get('password')
    
    users = DataManager.load(FILES['users'])
    
    if username in users:
        stored = users[username].get('password', '')
        # Support both new hashes and legacy plain text during migration
        valid = False
        if stored.startswith(('scrypt:', 'pbkdf2:')):
            valid = check_password_hash(stored, password)
        else:
            valid = (stored == password)
            
        if valid:
            session.permanent = True
            session['user'] = {'name': username, 'type': 'individual'}
            return redirect(url_for('index'))

    return render_template('login.html', error="Invalid credentials", mode="login")

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    
    if not username or not password:
        return render_template('login.html', error="Missing fields", mode="register")
        
    with DB_LOCK:
        users = DataManager.load(FILES['users'])
        if username in users:
            return render_template('login.html', error="Username taken", mode="register")
        
        users[username] = {
            "password": generate_password_hash(password),
            "type": "individual",
            "created_at": datetime.now().strftime('%Y-%m-%d')
        }
        DataManager.save(FILES['users'], users)
        
    session['user'] = {'name': username, 'type': 'individual'}
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- API ENDPOINTS (Robust & Error Safe) ---

@app.route('/api/inventory', methods=['GET'])
@login_required_api
def api_get_inventory():
    try:
        data = InventoryService.get_inventory(session['user']['name'])
        return jsonify(data)
    except Exception as e:
        logger.error(f"Inventory API Error: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/api/add_item', methods=['POST'])
@login_required_api
def api_add_item():
    data = get_valid_json()
    
    # Validation
    name = str(data.get('name', '')).strip()
    date = data.get('expiry_date')
    
    if not name or not date:
        return jsonify({"error": "Name and Date are required."}), 400
    
    try:
        data['name'] = name # Ensure trimmed name is used
        new_item = InventoryService.add_item(data, session['user']['name'])
        return jsonify({"success": True, "item": new_item})
    except Exception as e:
        logger.error(f"Add Item Error: {e}")
        return jsonify({"error": "Failed to save item"}), 500

@app.route('/api/delete_item', methods=['POST'])
@login_required_api
def api_delete_item():
    data = get_valid_json()
    item_id = data.get('id')
    
    if not item_id:
        return jsonify({"error": "Missing Item ID"}), 400
        
    try:
        success = InventoryService.delete_item(int(item_id), session['user']['name'])
        if success:
            return jsonify({"success": True})
        return jsonify({"error": "Item not found or access denied"}), 404
    except ValueError:
        return jsonify({"error": "Invalid ID format"}), 400

@app.route('/api/categories', methods=['GET'])
@login_required_api
def api_get_categories():
    try:
        cats = CategoryService.get_categories(session['user']['name'])
        return jsonify({"categories": cats})
    except Exception as e:
        logger.error(f"Category API Error: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/api/add_category', methods=['POST'])
@login_required_api
def api_add_category():
    data = get_valid_json()
    name = str(data.get('name', '')).strip()
    
    if not name:
        return jsonify({"error": "Category name missing"}), 400
    if len(name) > 30:
        return jsonify({"error": "Name too long (max 30 chars)"}), 400
        
    try:
        success, result = CategoryService.add_category(name, session['user']['name'])
        if success:
            return jsonify({"success": True, "category": result})
        return jsonify({"error": result}), 400 # 'result' contains error message here
    except Exception as e:
        logger.error(f"Add Category Error: {e}")
        return jsonify({"error": "Server error"}), 500

@app.route('/api/delete_category', methods=['POST'])
@login_required_api
def api_delete_category():
    data = get_valid_json()
    name = data.get('name')
    
    if not name:
        return jsonify({"error": "Missing name"}), 400
        
    try:
        success, msg = CategoryService.delete_category(name, session['user']['name'])
        if success:
            return jsonify({"success": True, "message": msg})
        return jsonify({"error": msg}), 403
    except Exception as e:
        logger.error(f"Delete Category Error: {e}")
        return jsonify({"error": "Server error"}), 500

# ==========================================
# 6. ENTRY POINT
# ==========================================
if __name__ == '__main__':
    # Initialize DB on start
    DataManager.ensure_directory()
    app.run(debug=True, port=5000)