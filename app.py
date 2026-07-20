from flask import Flask, render_template, request, redirect, url_for, make_response, g
import requests
import jwt
import os
from dotenv import load_dotenv
from functools import wraps
from collections import deque
import datetime

load_dotenv()

app = Flask(__name__)

app.config["JWT_SECRET_KEY"] = os.getenv("FLASK_JWT_SECRET_KEY")
app.secret_key = os.getenv("FLASK_SECRET_KEY")

API_BASE_URL = "http://localhost:5000"

def verify_token(token):
    if not token:
        return None
    try:
        payload = jwt.decode(token, app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        print("Token has expired.")
        return None
    except jwt.InvalidTokenError:
        print("Token signature is invalid.")
        return None

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('auth_token')
        user_data = verify_token(token)
        
        if not user_data:
            return redirect(url_for('login_page'))
            
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.cookies.get('auth_token')
        user_data = verify_token(token)
        
        if not user_data:
            return redirect(url_for('login_page'), code=303)
            
        if not user_data.get("is_admin"):
            return redirect(url_for('index'), code=303)
            
        return f(*args, **kwargs)
    return decorated_function

def get_user_context():
    token = request.cookies.get('auth_token')
    is_authenticated = False
    is_admin = False
    g.clear_expired_auth_token = False

    if token:
        try:
            decoded = jwt.decode(token, app.config["JWT_SECRET_KEY"], algorithms=["HS256"])
            is_authenticated = True
            is_admin = decoded.get('is_admin') is True
        except jwt.ExpiredSignatureError:
            print("Token has expired")
            g.clear_expired_auth_token = True
        except jwt.InvalidTokenError:
            print("Token is invalid")
            g.clear_expired_auth_token = True
        except Exception:
            pass

    return {
        "is_authenticated": is_authenticated,
        "is_admin": is_admin
    }

REQUEST_LOGS = deque(maxlen=100)

@app.after_request
def log_outgoing_request(response):
    if request.path.startswith('/static'):
        return response

    log_entry = {
        "ip": request.headers.get('X-Forwarded-For', request.remote_addr),
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
    }
    
    REQUEST_LOGS.appendleft(log_entry)
    return response

@app.after_request
def clear_expired_auth_tokens(response):
    if 'clear_expired_auth_token' in g and g.clear_expired_auth_token:
        response.delete_cookie('auth_token')
    return response

def get_all_coins_with_associated_duties():
    coins = []
    try:
        coins = requests.get(f"{API_BASE_URL}/api/v1/coins").json()
        
        for coin in coins:
            coin_id = coin["id"]
            duties_for_coin = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties").json()
            
            coin["duties"] = duties_for_coin.get("linked_to", [])
        coins.sort(key=lambda coin: coin["name"])
        
        return coins
    except requests.RequestException:
        return 'Error receiving API response', 500
    
def get_all_duties_with_associated_ksbs():
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/duties/with-ksbs")
        duties = response.json() if response.status_code == 200 else []
        
        return duties
    except requests.RequestException:
        print("Error fetching duties with associated KSBs.")
    return []

def get_all_ksbs():
    try:
        response = requests.get(f"{API_BASE_URL}/api/v1/ksb")
        if response.status_code == 200:
            data = response.json()
            data.sort(key=lambda x: (x.get('type'), x.get('name')))
            return data
    except requests.RequestException:
        print("Error fetching KSBs.")
    return []

@app.route('/')
def index():
    context = get_user_context()
    coins = get_all_coins_with_associated_duties()
    duties = get_all_duties_with_associated_ksbs()
    return render_template("index.html", coins=coins, duties=duties, **context)

@app.route('/login')
def login_page():
    if request.cookies.get('auth_token'):
        return redirect(url_for('index'))
    return render_template("login.html")

@app.route('/login', methods=['POST'])
def handle_login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if not username or not password:
        return render_template('login.html', error="Username and password are required.")

    try:
        backend_response = requests.post(
            f"{API_BASE_URL}/login", 
            json={"username": username, "password": password}
        )
        
        if backend_response.status_code == 200:
            token_data = backend_response.json()
            access_token = token_data.get('access_token')

            response = make_response(redirect(url_for('index')))
            
            response.set_cookie(
                'auth_token',
                access_token, 
                httponly=True,  
                samesite='Lax',
            )
            return response
            
        elif backend_response.status_code == 401:
            return render_template('login.html', error="Invalid username or password.")
        else:
            return render_template('login.html', error="An error occurred on the authorisation server.")

    except requests.RequestException as e:
        return render_template('login.html', error="Unable to reach the login service right now.")
    
@app.route('/logout', methods=['POST'])
def handle_logout():
    response = make_response(redirect(url_for('index')))
    response.delete_cookie('auth_token')
    
    return response

@app.route('/coins/<coin_id>', methods=['PATCH'])
@login_required
def update_coin_completion_status(coin_id):
    token = request.cookies.get('auth_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if not token:
        return 'Unauthorized user', 401
        
    try:
        patch_response = requests.patch(
            f"{API_BASE_URL}/api/v1/coins/{coin_id}",
            json=request.get_json(),
            headers=headers
        )
        return make_response(patch_response.text, patch_response.status_code)
    except requests.RequestException:
        return 'Server error', 500
    

@app.route('/manage-coin/<coin_id>', methods=['GET'])
@admin_required
def manage_coin_page(coin_id):
    context = get_user_context()
    if not context.get("is_admin"):
        return redirect(url_for('index'))

    coin_resp = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}")
    coin = coin_resp.json() if coin_resp.status_code == 200 else {}

    coin_duties_resp = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties")
    coin_duties = coin_duties_resp.json().get("linked_to", []) if coin_duties_resp.status_code == 200 else []

    all_duties = get_all_duties_with_associated_ksbs()

    coin = {
        "id": coin_id,
        "name": coin.get("name"),
        "duties": coin_duties
    }

    return render_template('manage_coin.html', coin=coin, all_duties=all_duties, **context)

@app.route('/coins/create', methods=['POST'])
@admin_required
def create_coin():
    token = request.cookies.get('auth_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    new_coin_name = request.form.get('new_coin_name', '').strip()
    if new_coin_name:
        try:
            requests.post(f"{API_BASE_URL}/api/v1/coins", json={"name": new_coin_name}, headers=headers)
        except requests.RequestException as e:
            print("Error trying to create coin: ", e)
            
    return redirect(url_for('index'))

@app.route('/manage-coin/<coin_id>/update', methods=['POST'])
@admin_required
def update_coin(coin_id):
    token = request.cookies.get('auth_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    submitted_name = request.form.get('name', '').strip()
    original_name = request.form.get('original_coin_name', '').strip()
    submitted_duty_ids = request.form.getlist('associated_duty_ids')

    # Update coin name only if it's been updated on the form
    if submitted_name and submitted_name != original_name:
        requests.patch(f"{API_BASE_URL}/api/v1/coins/{coin_id}", json={"name": submitted_name}, headers=headers)
    
    # Get all duties, and create a name:Id map of duties
    duties_resp = requests.get(f"{API_BASE_URL}/api/v1/duties")
    all_duties = duties_resp.json() if duties_resp.status_code == 200 else []
    name_to_id_map = {duty['name']: duty['id'] for duty in all_duties}

    # Get IDs of all associated duties for the coin using the duties name:Id map
    current_assoc_resp = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties")
    current_assoc = current_assoc_resp.json() if current_assoc_resp.status_code == 200 else {}
    currently_linked_names = current_assoc.get("linked_to", [])
    currently_linked_ids = [name_to_id_map[name] for name in currently_linked_names if name in name_to_id_map]

    # Associate new duties
    for duty_id in submitted_duty_ids:
        if duty_id not in currently_linked_ids:
            requests.post(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties/{duty_id}", headers=headers)

    # Remove duties that were unselected on the form
    for duty_id in currently_linked_ids:
        if duty_id not in submitted_duty_ids:
            requests.delete(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties/{duty_id}", headers=headers)

    return redirect(url_for('index'))

@app.route('/manage-coin/<coin_id>/delete', methods=['POST'])
@admin_required
def delete_coin(coin_id):
    token = request.cookies.get('auth_token')
    if not token: return 'Unauthorized', 401
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    try:
        response = requests.delete(f"{API_BASE_URL}/api/v1/coins/{coin_id}", headers=headers)
        if response.status_code == 200:
            return redirect(url_for('index'))
        return redirect(url_for('manage_coin_page', coin_id=coin_id))
    except requests.RequestException as e:
        print("Error trying to delete coin: ", e)

@app.route('/manage-duty/<duty_id>', methods=['GET'])
@admin_required
def manage_duty_page(duty_id):
    context = get_user_context()
    
    all_duties = get_all_duties_with_associated_ksbs()
    duty = next((duty for duty in all_duties if duty['id'] == duty_id), None)

    if not duty:
        return redirect(url_for('index'), code=303)
        
    all_ksbs = get_all_ksbs()
    associated_ksb_names = [ksb['name'] for ksb in duty.get('ksbs', [])]

    return render_template('manage_duty.html', duty=duty, all_ksbs=all_ksbs, associated_ksb_names=associated_ksb_names, **context)

@app.route('/duties/create', methods=['POST'])
@admin_required
def create_duty():
    token = request.cookies.get('auth_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    name = request.form.get('name').strip()
    description = request.form.get('description').strip()
    payload = {"name": name, "description": description}
    
    try:
        requests.post(f"{API_BASE_URL}/api/v1/duties", json=payload, headers=headers)
    except requests.RequestException as e:
        print("Error trying to create coin: ", e)
        
    return redirect(url_for('index'))

@app.route('/manage-duty/<duty_id>/update', methods=['POST'])
@admin_required
def update_duty(duty_id):
    token = request.cookies.get('auth_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    submitted_name = request.form.get('name', '').strip()
    submitted_desc = request.form.get('description', '').strip()
    
    original_name = request.form.get('original_duty_name', '').strip()
    original_desc = request.form.get('original_duty_description', '').strip()
    
    submitted_ksb_ids = request.form.getlist('associated_ksb_ids')

    metadata_payload = {}
    if submitted_name and submitted_name != original_name:
        metadata_payload["name"] = submitted_name
    if submitted_desc and submitted_desc != original_desc:
        metadata_payload["description"] = submitted_desc

    if metadata_payload:
        requests.patch(f"{API_BASE_URL}/api/v1/duties/{duty_id}", json=metadata_payload, headers=headers)
    
    current_assoc_resp = requests.get(f"{API_BASE_URL}/api/v1/duties/{duty_id}/ksb")
    current_assoc = current_assoc_resp.json() if current_assoc_resp.status_code == 200 else {}
    
    currently_linked_ids = [str(ksb['id']) for ksb in current_assoc.get("linked_to", []) if 'id' in ksb]

    for ksb_id in submitted_ksb_ids:
        if ksb_id not in currently_linked_ids:
            requests.post(f"{API_BASE_URL}/api/v1/duties/{duty_id}/ksb/{ksb_id}", headers=headers)

    for ksb_id in currently_linked_ids:
        if ksb_id not in submitted_ksb_ids:
            requests.delete(f"{API_BASE_URL}/api/v1/duties/{duty_id}/ksb/{ksb_id}", headers=headers)

    return redirect(url_for('index'))


@app.route('/manage-duty/<duty_id>/delete', methods=['POST'])
@admin_required
def delete_duty(duty_id):
    token = request.cookies.get('auth_token')
    if not token: return 'Unauthorized', 401
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    try:
        res = requests.delete(f"{API_BASE_URL}/api/v1/duties/{duty_id}", headers=headers)
        if res.status_code == 200:
            return redirect(url_for('index'))
        return redirect(url_for('manage_duty_page', duty_id=duty_id))
    except requests.RequestException as e:
        print("Error trying to delete duty: ", e)
        
    return redirect(url_for('index'), code=303)

@app.route('/logs')
@admin_required
def view_request_logs():
    context = get_user_context()
    
    return render_template('logs.html', logs=list(REQUEST_LOGS), **context)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)