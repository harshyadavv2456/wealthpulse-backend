import os
import time
import requests
import json
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from nsetools import Nse
from nsepy import get_history
import pybreaker
from flask_caching import Cache
from cryptography.fernet import Fernet
from dotenv import load_dotenv
import redis

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

# Initialize Redis
redis_client = redis.Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Initialize Cache
cache = Cache(config={
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_CLIENT': redis_client,
    'CACHE_KEY_PREFIX': 'wealthpulse_',
    'CACHE_DEFAULT_TIMEOUT': 300
})
cache.init_app(app)

# Helper Functions
def get_encryption_key():
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        if os.getenv('FLASK_ENV') != 'production':
            key = Fernet.generate_key().decode()
            os.environ['ENCRYPTION_KEY'] = key
            app.logger.warning("Generated temporary ENCRYPTION_KEY for development")
        else:
            raise RuntimeError("ENCRYPTION_KEY missing in production")
    return key.encode()

def encrypt_data(content):
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.encrypt(content.encode()).decode()
    except Exception as e:
        app.logger.error(f"Encryption failed: {str(e)}")
        return content

def decrypt_data(content):
    try:
        fernet = Fernet(get_encryption_key())
        return fernet.decrypt(content.encode()).decode()
    except Exception as e:
        app.logger.error(f"Decryption failed: {str(e)}")
        return content

def requires_disclaimer(query):
    investment_keywords = {'invest', 'stock', 'fund', 'buy', 'sell', 'crypto', 'portfolio'}
    return any(keyword in query.lower() for keyword in investment_keywords)

def get_indian_stock_price(symbol):
    try:
        quote = nse.get_quote(symbol)
        return quote['lastPrice'], quote['previousClose']
    except Exception as e:
        app.logger.error(f"NSE error for {symbol}: {str(e)}")
        return None, None

def get_international_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2d")
        if len(hist) >= 2:
            return hist['Close'].iloc[-1], hist['Close'].iloc[-2]
        return None, None
    except Exception as e:
        app.logger.error(f"YFinance error for {symbol}: {str(e)}")
        return None, None

def get_reliable_price(symbol):
    # For Indian stocks
    if symbol.endswith('.NS'):
        return get_indian_stock_price(symbol.replace('.NS', ''))
    # For indices and crypto
    return get_international_price(symbol)

def get_historical_data(symbol, period='1mo'):
    cache_key = f"hist_{symbol}_{period}"
    cached_data = redis_client.get(cache_key)
    if cached_data:
        return json.loads(decrypt_data(cached_data.decode()))
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            return []
        
        # Convert to list of [timestamp, close] pairs
        data = []
        for index, row in hist.iterrows():
            data.append({
                'time': index.strftime('%Y-%m-%d'),
                'value': row['Close']
            })
        
        # Cache for 1 hour
        redis_client.setex(cache_key, 3600, encrypt_data(json.dumps(data)))
        return data
    except Exception as e:
        app.logger.error(f"Historical data error: {str(e)}")
        return []

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

def calculate_sip(amount, years, return_rate):
    monthly_rate = return_rate / 12 / 100
    months = years * 12
    future_value = amount * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate)
    total_invested = amount * months
    returns = future_value - total_invested
    return {
        'invested_amount': total_invested,
        'estimated_returns': returns,
        'total_value': future_value
    }

# Routes
@app.route("/")
def index():
    return render_template('index.html')

@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

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
            {
                "id": "nifty",
                "name": "Nifty 50",
                "value": nifty_price,
                "change": nifty_change,
                "change_percent": nifty_change_percent
            },
            {
                "id": "sensex",
                "name": "SENSEX",
                "value": sensex_price,
                "change": sensex_change,
                "change_percent": sensex_change_percent
            },
            {
                "id": "btc",
                "name": "Bitcoin",
                "value": btc_price_inr,
                "change": btc_change * usd_to_inr,
                "change_percent": btc_change_percent
            },
            {
                "id": "eth",
                "name": "Ethereum",
                "value": eth_price_inr,
                "change": eth_change * usd_to_inr,
                "change_percent": eth_change_percent
            }
        ]
        
        return jsonify(indices)
    except Exception as e:
        app.logger.exception("Market overview error")
        return jsonify({"error": "Market data unavailable"}), 500

@app.route("/api/top-movers", methods=["GET"])
@cache.cached(timeout=300)
def top_movers():
    try:
        top_gainers = nse.get_top_gainers()[:10]
        return jsonify({
            "gainers": top_gainers,
            "updated": datetime.now().isoformat()
        })
    except Exception as e:
        app.logger.exception("Top movers error")
        return jsonify({"error": "Could not fetch top movers"}), 500

@app.route("/api/security/<symbol>", methods=["GET"])
def security_detail(symbol):
    try:
        # Try Indian stock first
        if not symbol.endswith('.NS'):
            try:
                quote = nse.get_quote(symbol)
                return jsonify({
                    "symbol": symbol,
                    "name": quote['companyName'],
                    "current_price": quote['lastPrice'],
                    "previous_close": quote['previousClose'],
                    "change": quote['change'],
                    "change_percent": quote['pChange'],
                    "type": "stock"
                })
            except:
                symbol += '.NS'
        
        # International symbol
        ticker = yf.Ticker(symbol)
        info = ticker.info
        hist = ticker.history(period="2d")
        
        if hist.empty:
            return jsonify({"error": "No data available"}), 404
        
        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current_price
        change = current_price - prev_close
        change_percent = (change / prev_close) * 100
        
        security_data = {
            "symbol": symbol,
            "name": info.get('longName', symbol),
            "current_price": current_price,
            "previous_close": prev_close,
            "change": change,
            "change_percent": change_percent,
            "type": "crypto" if 'cryptocurrency' in info.get('quoteType', '').lower() else "stock"
        }
        
        return jsonify(security_data)
    except Exception as e:
        app.logger.exception(f"Security detail error for {symbol}")
        return jsonify({"error": "Could not fetch security details"}), 500

@app.route("/api/historical/<symbol>", methods=["GET"])
def historical_data(symbol):
    period = request.args.get('period', '1mo')
    data = get_historical_data(symbol, period)
    return jsonify(data)

@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    try:
        data = request.json
        query = data.get("message", "").strip()
        if not query:
            return jsonify({"reply": "Please enter a question."})
        
        # Check cache first
        cache_key = f"ai_response:{query}"
        cached_response = redis_client.get(cache_key)
        if cached_response:
            return jsonify({"reply": decrypt_data(cached_response.decode())})
        
        # Prepare DeepSeek payload
        system_prompt = (
            "You are WealthPulse AI, an expert financial advisor for Indian markets. "
            "Provide detailed, accurate, and helpful responses about stocks, mutual funds, SIPs, and crypto. "
            "When discussing investments, include: "
            "'*SEBI Disclaimer: This is not investment advice. Consult a SEBI-registered advisor before making decisions.*'"
        )
        
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        # Call DeepSeek API
        response = call_deepseek_api(payload)
        ai_response = response['choices'][0]['message']['content']
        
        # Append disclaimer if needed
        if requires_disclaimer(query):
            ai_response += "\n\n*SEBI Disclaimer: This is not investment advice. Consult a SEBI-registered advisor before making decisions.*"
        
        # Cache response
        redis_client.setex(cache_key, 3600, encrypt_data(ai_response))
        
        return jsonify({"reply": ai_response})
    except pybreaker.CircuitBreakerError:
        return jsonify({"reply": "AI assistant is temporarily unavailable. Please try again later."}), 503
    except Exception as e:
        app.logger.exception("AI assistant error")
        return jsonify({"reply": "Sorry, I encountered an error processing your request"}), 500

@app.route("/api/sip/calculate", methods=["GET"])
def sip_calculate():
    try:
        amount = float(request.args.get('amount', 10000))
        years = float(request.args.get('years', 10))
        return_rate = float(request.args.get('return', 12))
        
        if amount <= 0 or years <= 0 or return_rate <= 0:
            return jsonify({"error": "Invalid parameters"}), 400
        
        result = calculate_sip(amount, years, return_rate)
        return jsonify(result)
    except Exception as e:
        app.logger.exception("SIP calculation error")
        return jsonify({"error": "Could not calculate SIP"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=os.getenv('FLASK_ENV') != 'production')
