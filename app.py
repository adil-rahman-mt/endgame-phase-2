from flask import Flask, render_template
import requests

app = Flask(__name__)

API_BASE_URL = "http://localhost:5000"

@app.route('/')
def index():
    try:
        coins_response = requests.get(f"{API_BASE_URL}/api/v1/coins")
        coins_data = coins_response.json()
        
        for coin in coins_data:
            coin_id = coin["id"]
            duties_response = requests.get(f"{API_BASE_URL}/api/v1/coins/{coin_id}/duties")
            duties_data = duties_response.json()
            
            coin["duties"] = duties_data.get("linked_to", [])
        return render_template("index.html", coins=coins_data)
    except requests.RequestException:
        return 'Error receiving API response', 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5005, debug=True)