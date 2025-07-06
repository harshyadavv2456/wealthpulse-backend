import os
import time
import requests
from datetime import datetime
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import yfinance as yf
from nsetools import Nse
import pybreaker
from flask_caching import Cache
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Initialize NSE
nse = Nse()

# Initialize Circuit Breaker
AI_BREAKER = pybreaker.CircuitBreaker(
    fail_max=int(os.getenv('AI_FAILURE_THRESHOLD', 3)),
    reset_timeout=60,
    name="DeepSeek_AI"
)

# Initialize Redis Cache
cache = Cache(config={
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    'CACHE_KEY_PREFIX': 'wealthpulse_',
    'CACHE_DEFAULT_TIMEOUT': 300
})

# Initialize Cache
cache.init_app(app)

# Helper Functions
def get_encryption_key():
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        # Generate key only in development
        if os.getenv('FLASK_ENV') != 'production':
            key = Fernet.generate_key().decode()
            os.environ['ENCRYPTION_KEY'] = key
            app.logger.warning("Generated temporary ENCRYPTION_KEY for development")
        else:
            raise RuntimeError("ENCRYPTION_KEY missing in production")
    return key.encode()

def encrypt_log_entry(content):
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.encrypt(content.encode())
    except Exception as e:
        app.logger.error(f"Encryption failed: {str(e)}")
        return content.encode()  # Return plaintext if encryption fails

def requires_disclaimer(query):
    investment_keywords = {'invest', 'stock', 'fund', 'buy', 'sell', 'crypto', 'portfolio'}
    return any(keyword in query.lower() for keyword in investment_keywords)

def get_reliable_price(symbol):
    try:
        # For Indian stocks
        if symbol.endswith('.NS'):
            stock_symbol = symbol.replace('.NS', '')
            quote = nse.get_quote(stock_symbol)
            return quote['lastPrice'], quote['previousClose']
        
        # For indices and crypto
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        if len(hist) >= 2:
            return hist['Close'].iloc[-1], hist['Close'].iloc[-2]
        return None, None
    except Exception as e:
        app.logger.error(f"Price fetch error for {symbol}: {str(e)}")
        return None, None

@AI_BREAKER
def call_deepseek_api(payload):
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY missing")
        
    DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    response = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=15)
    response.raise_for_status()
    return response.json()

# Routes
@app.route("/")
def index():
    return render_template('index.html')

@app.route("/api/market-overview", methods=["GET"])
@cache.cached(timeout=60)
def market_overview():
    try:
        # Get live data
        nifty_price, nifty_prev = get_reliable_price("^NSEI") or (22000, 21800)
        sensex_price, sensex_prev = get_reliable_price("^BSESN") or (73000, 72500)
        btc_price, btc_prev = get_reliable_price("BTC-USD") or (60000, 59000)
        eth_price, eth_prev = get_reliable_price("ETH-USD") or (3000, 2950)
        
        # Calculate changes
        nifty_change = nifty_price - nifty_prev
        nifty_change_percent = (nifty_change / nifty_prev) * 100
        sensex_change = sensex_price - sensex_prev
        sensex_change_percent = (sensex_change / sensex_prev) * 100
        btc_change = btc_price - btc_prev
        btc_change_percent = (btc_change / btc_prev) * 100
        eth_change = eth_price - eth_prev
        eth_change_percent = (eth_change / eth_prev) * 100
        
        # Convert to INR
        usd_to_inr = 83.5
        btc_price_inr = btc_price * usd_to_inr
        eth_price_inr = eth_price * usd_to_inr
        
        indices = [
            {"name": "Nifty 50", "value": nifty_price, "change": nifty_change, "change_percent": nifty_change_percent, "icon": "fas fa-chart-line"},
            {"name": "SENSEX", "value": sensex_price, "change": sensex_change, "change_percent": sensex_change_percent, "icon": "fas fa-chart-line"},
            {"name": "Bitcoin", "value": btc_price_inr, "change": btc_change * usd_to_inr, "change_percent": btc_change_percent, "icon": "fab fa-bitcoin"},
            {"name": "Ethereum", "value": eth_price_inr, "change": eth_change * usd_to_inr, "change_percent": eth_change_percent, "icon": "fab fa-ethereum"}
        ]
        
        return jsonify(indices)
    except Exception as e:
        app.logger.exception("Market overview error")
        return jsonify({"error": "Market data unavailable"}), 500

@app.route("/api/ai-assistant", methods=["POST"])
def ai_assistant():
    try:
        data = request.json
        query = data.get("query", "").strip().lower()
        if not query:
            return jsonify({"response": "Please enter a question."})
        
        # Check cache first
        cache_key = f"ai_response:{query}"
        cached_response = cache.get(cache_key)
        if cached_response:
            return jsonify({"response": cached_response})
        
        # Prepare DeepSeek payload
        system_prompt = (
            "You are an expert financial advisor for Indian markets. Provide detailed, accurate, and helpful responses about stocks, mutual funds, SIPs, and crypto. "
            "Always include SEBI disclaimer when discussing investments: '*Disclaimer: This is not investment advice. Please consult a SEBI-registered advisor before acting on this information.*'"
        )
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        
        # Call DeepSeek API
        response = call_deepseek_api(payload)
        ai_response = response['choices'][0]['message']['content']
        
        # Append disclaimer if needed
        if requires_disclaimer(query):
            ai_response += "\n\n*Disclaimer: This is not investment advice. Please consult a SEBI-registered advisor before acting on this information.*"
        
        # Encrypt and log
        try:
            log_entry = f"[{datetime.now()}] Query: {query}\nResponse: {ai_response}\n"
            encrypted_log = encrypt_log_entry(log_entry)
            with open("ai_logs.txt", "ab") as log_file:
                log_file.write(encrypted_log + b'\n')
        except Exception as e:
            app.logger.error(f"Logging failed: {str(e)}")
        
        # Cache response
        cache.set(cache_key, ai_response, timeout=3600)
        
        return jsonify({"response": ai_response})
    except pybreaker.CircuitBreakerError:
        return jsonify({"response": "AI assistant is temporarily unavailable. Please try again shortly."}), 503
    except Exception as e:
        app.logger.exception("AI assistant error")
        return jsonify({"response": "Sorry, I encountered an error processing your request"}), 500

@app.route("/api/ai-assistant/health", methods=["GET"])
def ai_health_check():
    start_time = time.time()
    try:
        # Test DeepSeek connection
        response = requests.get(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}"},
            timeout=3
        )
        latency_ms = int((time.time() - start_time) * 1000)
        
        if response.status_code == 200:
            return jsonify({
                "status": "online",
                "latency_ms": latency_ms
            }), 200
        else:
            return jsonify({
                "status": "offline",
                "latency_ms": latency_ms
            }), 500
    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        return jsonify({
            "status": "offline",
            "latency_ms": latency_ms,
            "error": str(e)
        }), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=os.getenv('FLASK_ENV') != 'production')
