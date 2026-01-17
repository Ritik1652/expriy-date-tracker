import pytest
import json
import os
import shutil
from datetime import datetime, timedelta
from app import app, DATA_DIR, FILES, load_json, save_json, ensure_data_directory

# --- Configuration ---
TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), 'test_data')

# --- Fixtures ---

@pytest.fixture
def client():
    """Configures the app for testing and provides a test client."""
    app.config['TESTING'] = True
    app.secret_key = 'test_secret'
    
    # 1. Redirect Data Paths to a Test Folder
    # We monkeypatch the constants in app.py logic by pointing the FILES dict to test paths
    global DATA_DIR, FILES
    
    # Override paths temporarily for tests
    original_data_dir = DATA_DIR
    original_files = FILES.copy()
    
    # Setup Test Directory
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR)
    os.makedirs(TEST_DATA_DIR)
    
    # Update global file paths to point to test dir
    FILES['users'] = os.path.join(TEST_DATA_DIR, 'users.json')
    FILES['fresh'] = os.path.join(TEST_DATA_DIR, 'fresh_inventory.json')
    FILES['expired'] = os.path.join(TEST_DATA_DIR, 'expired_inventory.json')
    
    # Initialize empty JSON files
    save_json(FILES['users'], {})
    save_json(FILES['fresh'], [])
    save_json(FILES['expired'], [])
    
    with app.test_client() as client:
        yield client
    
    # Teardown: Cleanup Test Data
    if os.path.exists(TEST_DATA_DIR):
        shutil.rmtree(TEST_DATA_DIR)
        
    # Restore paths (though not strictly necessary as process ends)
    FILES = original_files

@pytest.fixture
def auth_client(client):
    """Helper: Registers and logs in a test user."""
    client.post('/register', data={'username': 'testuser', 'password': 'password123'})
    client.post('/login', data={'username': 'testuser', 'password': 'password123'})
    return client

# --- Tests ---

# 1. Authentication Tests
def test_register_and_login(client):
    """Test user registration and login flow."""
    # Register
    res = client.post('/register', data={'username': 'newuser', 'password': '123'})
    assert res.status_code == 302 # Redirects to index
    
    # Logout
    client.get('/logout')
    
    # Login
    res = client.post('/login', data={'username': 'newuser', 'password': '123'})
    assert res.status_code == 302
    
    # Verify persistence
    users = load_json(FILES['users'])
    assert 'newuser' in users
    assert users['newuser']['password'] != '123' # Password must be hashed

def test_prevent_duplicate_user(client):
    """Ensure duplicate usernames are rejected."""
    client.post('/register', data={'username': 'duplicate', 'password': '123'})
    res = client.post('/register', data={'username': 'duplicate', 'password': '123'})
    assert b"Username taken" in res.data

# 2. Inventory API Tests
def test_add_item(auth_client):
    """Test adding an item to fresh inventory."""
    res = auth_client.post('/api/add_item', json={
        'name': 'Milk', 
        'expiry_date': '2030-01-01'
    })
    assert res.status_code == 200
    
    data = load_json(FILES['fresh'])
    assert len(data) == 1
    assert data[0]['name'] == 'Milk'
    assert data[0]['owner'] == 'testuser'

def test_delete_item(auth_client):
    """Test deleting an item owned by the user."""
    # Add item
    auth_client.post('/api/add_item', json={'name': 'Bread', 'expiry_date': '2030-01-01'})
    items = load_json(FILES['fresh'])
    item_id = items[0]['id']
    
    # Delete item
    res = auth_client.post('/api/delete_item', json={'id': item_id})
    assert res.json['success'] is True
    
    # Verify empty
    data = load_json(FILES['fresh'])
    assert len(data) == 0

def test_data_isolation(client):
    """Security: User A should not see or delete User B's items."""
    # User A adds item
    client.post('/register', data={'username': 'UserA', 'password': '123'})
    client.post('/api/add_item', json={'name': 'UserA_Milk', 'expiry_date': '2030-01-01'})
    client.get('/logout')
    
    # User B logs in
    client.post('/register', data={'username': 'UserB', 'password': '123'})
    
    # Check Inventory (Should be empty)
    res = client.get('/api/inventory')
    data = res.json
    assert len(data['fresh']) == 0 # User B sees nothing
    
    # Try to delete User A's item (Manually getting ID from file)
    user_a_item = load_json(FILES['fresh'])[0]
    res = client.post('/api/delete_item', json={'id': user_a_item['id']})
    
    # Deletion should fail/not happen (logic in delete endpoint usually returns success=False or just keeps item)
    # Let's verify the file still has the item
    fresh_data = load_json(FILES['fresh'])
    assert len(fresh_data) == 1
    assert fresh_data[0]['name'] == 'UserA_Milk'

# 3. Expiry & Logic Tests
def test_expiry_sweep(auth_client):
    """Test that items move from Fresh -> Expired automatically."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Add expired item manually to file to simulate time passing
    # (Since API validates, we bypass API for this edge case setup)
    expired_item = {
        "id": 100,
        "name": "Old Cheese",
        "expiry_date": yesterday,
        "owner": "testuser",
        "added_at": "2020-01-01"
    }
    save_json(FILES['fresh'], [expired_item])
    
    # Trigger Sweep via GET request
    res = auth_client.get('/api/inventory')
    
    # Verify Fresh is empty
    assert len(res.json['fresh']) == 0
    # Verify Expired has item
    assert len(res.json['expired']) == 1
    assert res.json['expired'][0]['name'] == "Old Cheese"

def test_30_day_purge(auth_client):
    """Test that expired items > 30 days old are permanently deleted."""
    old_date = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
    
    # Manually seed expired list with an ancient item
    ancient_item = {
        "id": 999,
        "name": "Ancient Artifact",
        "expiry_date": old_date,
        "owner": "testuser",
        "archived_at": old_date
    }
    save_json(FILES['expired'], [ancient_item])
    
    # Trigger Sweep
    res = auth_client.get('/api/inventory')
    
    # Verify Deleted
    assert len(res.json['expired']) == 0