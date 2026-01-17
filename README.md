# 📦 Expiry Tracker - Inventory Health System

> "Stop selling a list. Sell inventory health."

A robust, secure, and intelligent inventory management system designed to track expiry risk rather than just listing items. This application evaluates risk daily, separating "Attention Required" items from "Stable Inventory" to ensure safety and reduce waste.

## 🚀 Key Features

* **Risk-First Dashboard:** Instantly separates items into *Urgent* (≤ 3 days), *Expired*, and *Safe*.
* **Expiry Intelligence:** Server-side logic automatically moves items to "Expired" status at midnight.
* **Safety Protocol:** "Do Not Use" lockouts for expired items (prevents accidental deletion/usage).
* **30-Day Auto-Purge:** Automatically deletes expired data after 30 days to maintain system hygiene.
* **Data Isolation:** Secure multi-user architecture; User A cannot see User B's inventory.
* **Race-Condition Handling:** Atomic writes and UI locks prevent data corruption during rapid actions.

## 🛠️ Tech Stack

* **Backend:** Python (Flask), Threading (Concurrency), Werkzeug (Security)
* **Frontend:** Vanilla JavaScript (ES6+), CSS3 (Variables & Optimizations)
* **Data:** JSON-based flat-file database with atomic locking.
* **Testing:** Pytest suite for security and logic verification.

## 📦 Installation

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/YOUR_USERNAME/expiry-tracker.git](https://github.com/YOUR_USERNAME/expiry-tracker.git)
    cd expiry-tracker
    ```

2.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the Application**
    ```bash
    python app.py
    ```
    *The server will start at `http://127.0.0.1:5000`*

## 🧪 Running Tests
This project includes a comprehensive test suite covering security, isolation, and expiry logic.
```bash
pytest
