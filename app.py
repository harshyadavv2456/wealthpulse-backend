from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
from datetime import datetime, timedelta
import requests
import numpy as np
import pandas as pd
import re
import time
import threading
from scipy import stats

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Cache system
data_cache = {
    'stocks': {},
    'mutual_funds': {},
    'crypto': {},
    'top_movers': {'last_updated': None, 'data': None},
    'market_overview': {'last_updated': None, 'data': None}
}

# Cache expiration times (seconds)
CACHE_EXPIRY = {
    'stocks': 300,
    'mutual_funds': 3600,
    'crypto': 300,
    'top_movers': 300,
    'market_overview': 60
}

# Load mutual fund data
def load_mutual_fund_data():
    try:
        print("Loading mutual fund data...")
        response = requests.get('https://api.mfapi.in/mf')
        if response.status_code == 200:
            funds = response.json()
            for fund in funds:
                data_cache['mutual_funds'][fund['schemeCode']] = {
                    'name': fund['schemeName'],
                    'category': fund.get('schemeCategory', ''),
                    'type': fund.get('schemeType', ''),
                    'last_updated': datetime.now()
                }
            print(f"Loaded {len(funds)} mutual funds")
    except Exception as e:
        print(f"Error loading mutual fund data: {str(e)}")

# Background thread for mutual funds
threading.Thread(target=lambda: [load_mutual_fund_data(), time.sleep(86400)], daemon=True).start()

# Market Overview Endpoint
@app.route("/api/market-overview", methods=["GET"])
def market_overview():
    try:
        # Check cache
        if data_cache['market_overview']['data'] and data_cache['market_overview']['last_updated']:
            cache_age = (datetime.now() - data_cache['market_overview']['last_updated']).total_seconds()
            if cache_age < CACHE_EXPIRY['market_overview']:
                return jsonify(data_cache['market_overview']['data'])
        
        # Get live data
        nifty = yf.Ticker("^NSEI")
        sensex = yf.Ticker("^BSESN")
        btc = yf.Ticker("BTC-USD")
        eth = yf.Ticker("ETH-USD")
        
        # Format for INR
        def format_inr(value):
            return f"₹{value:,.2f}" if value > 1000 else f"₹{value:.2f}"
        
        indices = [
            {
                "name": "Nifty 50",
                "value": nifty.fast_info.last_price,
                "change": nifty.fast_info.last_price - nifty.fast_info.previous_close,
                "change_percent": ((nifty.fast_info.last_price - nifty.fast_info.previous_close) / nifty.fast_info.previous_close) * 100,
                "icon": "fas fa-chart-line"
            },
            {
                "name": "SENSEX",
                "value": sensex.fast_info.last_price,
                "change": sensex.fast_info.last_price - sensex.fast_info.previous_close,
                "change_percent": ((sensex.fast_info.last_price - sensex.fast_info.previous_close) / sensex.fast_info.previous_close) * 100,
                "icon": "fas fa-chart-line"
            },
            {
                "name": "Bitcoin",
                "value": btc.fast_info.last_price * 83.5,  # Convert to INR
                "change": (btc.fast_info.last_price - btc.fast_info.previous_close) * 83.5,
                "change_percent": ((btc.fast_info.last_price - btc.fast_info.previous_close) / btc.fast_info.previous_close) * 100,
                "icon": "fab fa-bitcoin"
            },
            {
                "name": "Ethereum",
                "value": eth.fast_info.last_price * 83.5,  # Convert to INR
                "change": (eth.fast_info.last_price - eth.fast_info.previous_close) * 83.5,
                "change_percent": ((eth.fast_info.last_price - eth.fast_info.previous_close) / eth.fast_info.previous_close) * 100,
                "icon": "fab fa-ethereum"
            }
        ]
        
        # Update cache
        data_cache['market_overview']['data'] = indices
        data_cache['market_overview']['last_updated'] = datetime.now()
        
        return jsonify(indices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top Mutual Funds Endpoint
@app.route("/api/top-mf", methods=["GET"])
def top_mf():
    try:
        # For demo - would come from your MF data analysis
        top_funds = [
            {
                "id": "120503",
                "name": "Parag Parikh Flexi Cap Fund",
                "category": "Flexi Cap",
                "plan": "Direct Plan",
                "option": "Growth",
                "rating": "★★★★★",
                "ratingClass": "excellent",
                "ratingText": "Excellent",
                "returns": [
                    {"period": "1M", "value": 2.1},
                    {"period": "3M", "value": 8.4},
                    {"period": "6M", "value": 14.2},
                    {"period": "1Y", "value": 24.5},
                    {"period": "3Y", "value": 18.2},
                    {"period": "5Y", "value": 15.8}
                ]
            },
            {
                "id": "100366",
                "name": "SBI Small Cap Fund",
                "category": "Small Cap",
                "plan": "Direct Plan",
                "option": "Growth",
                "rating": "★★★★☆",
                "ratingClass": "good",
                "ratingText": "Good",
                "returns": [
                    {"period": "1M", "value": 1.8},
                    {"period": "3M", "value": 7.2},
                    {"period": "6M", "value": 16.5},
                    {"period": "1Y", "value": 32.1},
                    {"period": "3Y", "value": 24.8},
                    {"period": "5Y", "value": 21.3}
                ]
            }
        ]
        return jsonify(top_funds)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top Stocks Endpoint
@app.route("/api/top-stocks", methods=["GET"])
def top_stocks():
    try:
        top_stocks = [
            {
                "symbol": "RELIANCE.NS",
                "name": "Reliance Industries",
                "sector": "Energy",
                "exchange": "NSE",
                "price": 2845.50,
                "change": 2.1,
                "returns": [
                    {"period": "1D", "value": 1.2},
                    {"period": "1W", "value": 3.4},
                    {"period": "1M", "value": 8.2},
                    {"period": "3M", "value": 12.5},
                    {"period": "1Y", "value": 24.8},
                    {"period": "YTD", "value": 18.3}
                ]
            },
            {
                "symbol": "TCS.NS",
                "name": "Tata Consultancy Services",
                "sector": "IT Services",
                "exchange": "NSE",
                "price": 3450.75,
                "change": 1.8,
                "returns": [
                    {"period": "1D", "value": 0.8},
                    {"period": "1W", "value": 2.1},
                    {"period": "1M", "value": 5.6},
                    {"period": "3M", "value": 10.2},
                    {"period": "1Y", "value": 18.7},
                    {"period": "YTD", "value": 12.4}
                ]
            }
        ]
        return jsonify(top_stocks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top Crypto Endpoint
@app.route("/api/top-crypto", methods=["GET"])
def top_crypto():
    try:
        top_crypto = [
            {
                "symbol": "BTC-USD",
                "name": "Bitcoin",
                "price": 5241300,
                "change": -1.2,
                "returns": [
                    {"period": "1D", "value": -1.2},
                    {"period": "1W", "value": 3.8},
                    {"period": "1M", "value": 12.4},
                    {"period": "3M", "value": 24.5},
                    {"period": "1Y", "value": 85.2},
                    {"period": "YTD", "value": 42.1}
                ]
            },
            {
                "symbol": "ETH-USD",
                "name": "Ethereum",
                "price": 281500,
                "change": 0.78,
                "returns": [
                    {"period": "1D", "value": 0.5},
                    {"period": "1W", "value": 2.8},
                    {"period": "1M", "value": 9.4},
                    {"period": "3M", "value": 18.2},
                    {"period": "1Y", "value": 62.3},
                    {"period": "YTD", "value": 31.7}
                ]
            }
        ]
        return jsonify(top_crypto)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# AI Assistant Endpoint
@app.route("/api/ai-assistant", methods=["POST"])
def ai_assistant():
    try:
        data = request.json
        query = data.get("query", "")
        
        # AI response logic
        responses = {
            "stock": "Technology and renewable energy sectors are showing strong growth. Banking and infrastructure are also performing well due to government initiatives.",
            "fund": "For mutual funds, focus on consistent performers with low expense ratios. Flexi cap funds like Parag Parikh Flexi Cap have shown strong performance. For sector-specific exposure, consider technology-focused funds.",
            "crypto": "Cryptocurrency markets remain volatile but show long-term potential. Bitcoin and Ethereum continue to dominate the market. Always practice risk management in crypto investments.",
            "portfolio": "For portfolio balancing, consider a diversified approach: 50% equities (mix of large, mid and small caps), 30% fixed income/debt funds, 15% gold, and 5% crypto. Rebalance quarterly to maintain your target allocation.",
            "default": "I've analyzed your query and found that diversification remains key in the current market environment. Consider a balanced approach with 60% equities, 30% fixed income, and 10% alternatives. Rebalance quarterly to maintain your target allocation."
        }
        
        response = responses["default"]
        if "stock" in query.lower() or "equity" in query.lower():
            response = responses["stock"]
        elif "fund" in query.lower() or "mf" in query.lower():
            response = responses["fund"]
        elif "crypto" in query.lower():
            response = responses["crypto"]
        elif "portfolio" in query.lower() or "balance" in query.lower():
            response = responses["portfolio"]
            
        return jsonify({"response": response})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# SIP Calculator Endpoint
@app.route("/api/sip/calculate", methods=["GET"])
def calculate_sip():
    try:
        amount = float(request.args.get('amount', 10000))
        years = int(request.args.get('years', 10))
        rate = float(request.args.get('return', 12))
        
        monthly_rate = rate / 100 / 12
        months = years * 12
        future_value = amount * ((((1 + monthly_rate) ** months) - 1) / monthly_rate) * (1 + monthly_rate)
        total_investment = amount * months
        returns = future_value - total_investment
        
        return jsonify({
            "future_value": round(future_value, 2),
            "total_investment": total_investment,
            "returns": round(returns, 2)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Health Check
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    load_mutual_fund_data()
    app.run(host="0.0.0.0", port=8000, threaded=True)
