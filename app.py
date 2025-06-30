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

# Get reliable stock price
def get_reliable_price(ticker):
    try:
        # First try to get from fast_info
        if ticker.fast_info and ticker.fast_info.last_price:
            return ticker.fast_info.last_price, ticker.fast_info.previous_close
        
        # Fallback to history
        hist = ticker.history(period="2d")
        if len(hist) >= 2:
            return hist['Close'].iloc[-1], hist['Close'].iloc[-2]
        
        # Last resort
        return ticker.info['regularMarketPrice'], ticker.info['previousClose']
    except:
        try:
            # Final attempt with different method
            return ticker.info['currentPrice'], ticker.info['previousClose']
        except:
            return None, None

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
        
        # Get reliable prices
        nifty_price, nifty_prev = get_reliable_price(nifty)
        sensex_price, sensex_prev = get_reliable_price(sensex)
        btc_price, btc_prev = get_reliable_price(btc)
        eth_price, eth_prev = get_reliable_price(eth)
        
        # Calculate changes
        def calculate_change(current, previous):
            if current is None or previous is None:
                return 0, 0
            change = current - previous
            change_percent = (change / previous) * 100
            return change, change_percent
        
        nifty_change, nifty_change_percent = calculate_change(nifty_price, nifty_prev)
        sensex_change, sensex_change_percent = calculate_change(sensex_price, sensex_prev)
        btc_change, btc_change_percent = calculate_change(btc_price, btc_prev)
        eth_change, eth_change_percent = calculate_change(eth_price, eth_prev)
        
        # Format for INR
        def format_inr(value):
            if value is None:
                return "N/A"
            if value > 1000:
                return f"₹{value:,.2f}"
            return f"₹{value:.2f}"
        
        indices = [
            {
                "name": "Nifty 50",
                "value": nifty_price,
                "change": nifty_change,
                "change_percent": nifty_change_percent,
                "icon": "fas fa-chart-line"
            },
            {
                "name": "SENSEX",
                "value": sensex_price,
                "change": sensex_change,
                "change_percent": sensex_change_percent,
                "icon": "fas fa-chart-line"
            },
            {
                "name": "Bitcoin",
                "value": btc_price * 83.5 if btc_price else None,  # Convert to INR
                "change": (btc_change * 83.5) if btc_change else None,
                "change_percent": btc_change_percent,
                "icon": "fab fa-bitcoin"
            },
            {
                "name": "Ethereum",
                "value": eth_price * 83.5 if eth_price else None,  # Convert to INR
                "change": (eth_change * 83.5) if eth_change else None,
                "change_percent": eth_change_percent,
                "icon": "fab fa-ethereum"
            }
        ]
        
        # Update cache
        data_cache['market_overview']['data'] = indices
        data_cache['market_overview']['last_updated'] = datetime.now()
        
        return jsonify(indices)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Mutual Fund Detail Endpoint
@app.route("/api/mf/<scheme_code>", methods=["GET"])
def mutual_fund_detail(scheme_code):
    try:
        # Check cache first
        if scheme_code in data_cache['mutual_funds']:
            fund_data = data_cache['mutual_funds'][scheme_code]
            
            # Fetch NAV history
            nav_response = requests.get(f'https://api.mfapi.in/mf/{scheme_code}')
            if nav_response.status_code == 200:
                nav_data = nav_response.json()
                fund_data['nav_history'] = nav_data.get('data', [])
                
                # Calculate returns
                returns = calculate_mf_returns(fund_data['nav_history'])
                fund_data['returns'] = returns
                
                return jsonify(fund_data)
        
        return jsonify({"error": "Fund not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Calculate mutual fund returns
def calculate_mf_returns(nav_history):
    if not nav_history or len(nav_history) < 2:
        return {}
    
    # Parse NAV data
    parsed_nav = []
    for entry in nav_history:
        try:
            date = datetime.strptime(entry['date'], '%d-%m-%Y')
            nav = float(entry['nav'])
            parsed_nav.append((date, nav))
        except:
            continue
    
    if not parsed_nav:
        return {}
    
    # Sort by date
    parsed_nav.sort(key=lambda x: x[0])
    latest_date, latest_nav = parsed_nav[-1]
    
    # Calculate returns for different periods
    periods = {
        '1M': timedelta(days=30),
        '3M': timedelta(days=90),
        '6M': timedelta(days=180),
        '1Y': timedelta(days=365),
        '3Y': timedelta(days=3*365),
        '5Y': timedelta(days=5*365)
    }
    
    returns = {}
    for period, delta in periods.items():
        target_date = latest_date - delta
        # Find closest date to target
        closest = None
        for date, nav in parsed_nav:
            if date <= target_date:
                closest = nav
            else:
                break
        
        if closest and closest > 0:
            returns[period] = ((latest_nav - closest) / closest) * 100
    
    return returns

# Top Mutual Funds Endpoint
@app.route("/api/top-mf", methods=["GET"])
def top_mf():
    try:
        # Get category from query params
        category = request.args.get('category', 'equity')
        
        # For demo - real implementation would filter by category
        top_funds = []
        for code, fund in list(data_cache['mutual_funds'].items())[:5]:
            # Fetch fund details
            detail_response = mutual_fund_detail(code)
            if detail_response.status_code == 200:
                fund_data = detail_response.json
                fund_data['id'] = code
                top_funds.append(fund_data)
        
        return jsonify(top_funds[:2])  # Return top 2 for dashboard
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top Stocks Endpoint
@app.route("/api/top-stocks", methods=["GET"])
def top_stocks():
    try:
        # Predefined list of top Indian stocks
        symbols = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "HINDUNILVR.NS"]
        top_stocks = []
        
        for symbol in symbols[:2]:  # Only process first 2 for dashboard
            stock = yf.Ticker(symbol)
            info = stock.info
            
            # Get reliable price
            price, prev_close = get_reliable_price(stock)
            change = price - prev_close if price and prev_close else 0
            change_percent = (change / prev_close) * 100 if prev_close else 0
            
            stock_data = {
                "symbol": symbol,
                "name": info.get('longName', symbol),
                "sector": info.get('sector', ''),
                "exchange": "NSE",
                "price": price,
                "change": change,
                "change_percent": change_percent,
                "returns": []  # Would be calculated from history
            }
            top_stocks.append(stock_data)
        
        return jsonify(top_stocks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top Crypto Endpoint
@app.route("/api/top-crypto", methods=["GET"])
def top_crypto():
    try:
        symbols = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD"]
        top_crypto = []
        
        for symbol in symbols[:2]:  # Only process first 2 for dashboard
            crypto = yf.Ticker(symbol)
            info = crypto.info
            
            # Get reliable price
            price, prev_close = get_reliable_price(crypto)
            change = price - prev_close if price and prev_close else 0
            change_percent = (change / prev_close) * 100 if prev_close else 0
            
            crypto_data = {
                "symbol": symbol,
                "name": info.get('name', symbol),
                "price": price * 83.5 if price else None,  # Convert to INR
                "change": change * 83.5 if change else None,
                "change_percent": change_percent,
                "returns": []  # Would be calculated from history
            }
            top_crypto.append(crypto_data)
        
        return jsonify(top_crypto)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Mutual Fund Search Endpoint
@app.route("/api/mf/search", methods=["GET"])
def search_mf():
    try:
        query = request.args.get('query', '').lower()
        results = []
        
        for code, fund in data_cache['mutual_funds'].items():
            if query in fund['name'].lower():
                results.append({
                    "schemeCode": code,
                    "name": fund['name'],
                    "category": fund['category']
                })
        
        return jsonify(results[:5])  # Return top 5 matches
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Security Detail Endpoint
@app.route("/api/security/<symbol>", methods=["GET"])
def security_detail(symbol):
    try:
        # Determine security type
        if symbol.isdigit():
            # Mutual fund
            return mutual_fund_detail(symbol)
        elif symbol.endswith('.NS'):
            # Stock
            stock = yf.Ticker(symbol)
            info = stock.info
            
            # Get reliable price
            price, prev_close = get_reliable_price(stock)
            change = price - prev_close if price and prev_close else 0
            change_percent = (change / prev_close) * 100 if prev_close else 0
            
            return jsonify({
                "type": "stock",
                "symbol": symbol,
                "name": info.get('longName', symbol),
                "price": price,
                "change": change,
                "change_percent": change_percent,
                "sector": info.get('sector', ''),
                "marketCap": info.get('marketCap', 0),
                "peRatio": info.get('trailingPE', 0),
                "dividendYield": info.get('dividendYield', 0)
            })
        else:
            # Crypto
            crypto = yf.Ticker(symbol)
            info = crypto.info
            
            # Get reliable price
            price, prev_close = get_reliable_price(crypto)
            change = price - prev_close if price and prev_close else 0
            change_percent = (change / prev_close) * 100 if prev_close else 0
            
            return jsonify({
                "type": "crypto",
                "symbol": symbol,
                "name": info.get('name', symbol),
                "price": price * 83.5 if price else None,  # Convert to INR
                "change": change * 83.5 if change else None,
                "change_percent": change_percent,
                "marketCap": info.get('marketCap', 0),
                "volume": info.get('volume', 0)
            })
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
