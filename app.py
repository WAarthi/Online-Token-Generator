from flask import Flask, request, jsonify
from datetime import datetime
from flask_cors import CORS
import sqlite3
from contextlib import closing

app = Flask(__name__)
app.config["DEBUG"] = True
# Configure CORS properly
CORS(app, resources={
    r"/generate_token": {"origins": "*"},
    r"/queue": {"origins": "*"},
    r"/clear_orders": {"origins": "*"}
})

# Database configuration
DATABASE = 'udipi_orders.db'

def init_db():
    with closing(sqlite3.connect(DATABASE)) as conn:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_number INTEGER NOT NULL,
                    customer_id TEXT NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    price REAL NOT NULL,
                    amount REAL NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tokens (
                    token_number INTEGER PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    total_amount REAL NOT NULL
                )
            """)
            # Initialize token counter to start from 1000 if empty
            conn.execute("INSERT OR IGNORE INTO tokens (token_number, customer_id, timestamp, total_amount) VALUES (999, 'SYSTEM', '2000-01-01T00:00:00', 0)")

# Initialize database before first request
with app.app_context():
    init_db()

def get_db():
    return sqlite3.connect(DATABASE)

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "endpoints": {
            "/generate_token": "POST - Create new order",
            "/queue": "GET - Get current queue",
            "/clear_orders": "POST - Clear all orders (admin)"
        }
    })

@app.route('/generate_token', methods=['POST', 'OPTIONS'])
def generate_token():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        data = request.get_json()
        
        # Validate input
        if not data or 'items' not in data or 'customer_id' not in data:
            return jsonify({"error": "Invalid order data"}), 400
        
        # Filter items with quantity > 0
        valid_items = {k: v for k, v in data['items'].items() if v['quantity'] > 0}
        if not valid_items:
            return jsonify({"error": "No items in order"}), 400
        
        current_time = datetime.now().isoformat()
        formatted_time = datetime.now().strftime("%d %b %Y, %I:%M %p")
        
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get the next token number
            cursor.execute("SELECT MAX(token_number) FROM tokens")
            max_token = cursor.fetchone()[0]
            token_number = (max_token or 999) + 1
            
            # Create order entries
            order_entries = []
            total_amount = 0
            
            for item_name, details in valid_items.items():
                quantity = details['quantity']
                price = details['price']
                amount = quantity * price
                
                cursor.execute("""
                    INSERT INTO orders 
                    (token_number, customer_id, item_name, quantity, price, amount, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (token_number, data['customer_id'], item_name, quantity, price, amount, current_time))
                
                order_entries.append({
                    'item_name': item_name,
                    'quantity': quantity,
                    'price': price,
                    'amount': amount
                })
                
                total_amount += amount
            
            # Store token summary
            cursor.execute("""
                INSERT INTO tokens (token_number, customer_id, timestamp, total_amount)
                VALUES (?, ?, ?, ?)
            """, (token_number, data['customer_id'], current_time, total_amount))
            
            response = jsonify({
                'status': 'success',
                'token_number': token_number,
                'timestamp': current_time,
                'total': total_amount,
                'items': order_entries,
                'customer_id': data['customer_id'],
                'formatted_time': formatted_time
            })
            
            return _corsify_actual_response(response), 200
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/queue', methods=['GET', 'OPTIONS'])
def get_queue():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Get all unique token numbers with their details
            cursor.execute("""
                SELECT t.token_number, t.customer_id, t.timestamp, t.total_amount,
                       o.item_name, o.quantity, o.price
                FROM tokens t
                JOIN orders o ON t.token_number = o.token_number
                ORDER BY t.timestamp DESC
            """)
            
            orders = cursor.fetchall()
            
            # Group orders by token number
            unique_orders = {}
            for order in orders:
                token_num = order[0]
                if token_num not in unique_orders:
                    unique_orders[token_num] = {
                        'token_number': token_num,
                        'customer_id': order[1],
                        'timestamp': order[2],
                        'total': order[3],
                        'items': [{
                            'item_name': order[4],
                            'quantity': order[5],
                            'price': order[6]
                        }]
                    }
                else:
                    unique_orders[token_num]['items'].append({
                        'item_name': order[4],
                        'quantity': order[5],
                        'price': order[6]
                    })
            
            response = jsonify({
                'queue': list(unique_orders.values())
            })
            
            return _corsify_actual_response(response)
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/clear_orders', methods=['POST', 'OPTIONS'])
def clear_orders():
    if request.method == 'OPTIONS':
        return _build_cors_preflight_response()
    
    try:
        with get_db() as conn:
            with conn:
                conn.execute("DELETE FROM orders")
                conn.execute("DELETE FROM tokens")
                conn.execute("INSERT OR IGNORE INTO tokens (token_number, customer_id, timestamp, total_amount) VALUES (999, 'SYSTEM', '2000-01-01T00:00:00', 0)")
        return jsonify({"status": "success", "message": "All orders cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# CORS support functions
def _build_cors_preflight_response():
    response = jsonify({"status": "success"})
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

def _corsify_actual_response(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005)