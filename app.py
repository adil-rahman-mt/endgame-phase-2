from flask import Flask, render_template, request, redirect, url_for, make_response
import requests

app = Flask(__name__)

API_BASE_URL = "http://localhost:5000"

@app.route('/')
def index():
    token = request.cookies.get('auth_token')
    is_authenticated = True if token else False

    try:
        coins_response = requests.get(f"{API_BASE_URL}/api/v1/coins")
        coins_data = coins_response.json()
        
        for coin in coins_data:
            coin_id = coin["id"]
            duties_response = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties")
            duties_data = duties_response.json()
            
            coin["duties"] = duties_data.get("linked_to", [])
        return render_template("index.html", coins=coins_data, is_authenticated=is_authenticated)
    except requests.RequestException:
        return 'Error receiving API response', 500

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
def update_coin_completion(coin_id):
    token = request.cookies.get('auth_token')
    if not token:
        return 'Unauthorized user', 401
        
    try:
        patch_response = requests.patch(
            f"{API_BASE_URL}/api/v1/coins/{coin_id}",
            json=request.get_json(),
            headers={"Authorization": f"Bearer {token}"}
        )
        return make_response(patch_response.text, patch_response.status_code)
    except requests.RequestException:
        return 'Server error', 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)