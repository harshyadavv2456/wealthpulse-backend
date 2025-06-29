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

app = Flask(__name__)
CORS(app)

# Cache system for all data types
data_cache = {
    'stocks': {},
    'mutual_funds': {},
    'crypto': {},
    'top_movers': {'last_updated': None, 'data': None}
}

# Cache expiration times (seconds)
CACHE_EXPIRY = {
    'stocks': 300,
    'mutual_funds': 3600,
    'crypto': 300,
    'top_movers': 300
}

# Load mutual fund data on startup
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

# Background thread to refresh mutual fund data
def refresh_mf_data():
    while True:
        load_mutual_fund_data()
        time.sleep(86400)  # Refresh daily

# Start background thread
threading.Thread(target=refresh_mf_data, daemon=True).start()

# Enhanced stock analysis with multiple data sources
@app.route("/api/security/<ticker>", methods=["GET"])
def get_security(ticker):
    try:
        # Check cache first
        if ticker in data_cache['stocks']:
            cached_data = data_cache['stocks'][ticker]
            cache_age = (datetime.now() - cached_data['timestamp']).total_seconds()
            if cache_age < CACHE_EXPIRY['stocks']:
                return jsonify(cached_data['data'])
        
        # Determine security type
        if '-' in ticker:
            return get_crypto(ticker.split('-')[0])
        elif ticker.isdigit():
            return get_mutual_fund(ticker)
        else:
            return get_stock(ticker)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        updated_time = datetime.now()
        
        # Basic data
        name = info.get('longName', ticker.upper())
        symbol = ticker.upper()
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
        currency = info.get('currency', 'USD')
        
        # Calculate change
        if all(isinstance(x, (int, float)) for x in [current_price, previous_close]):
            change = round(current_price - previous_close, 2)
            change_percent = round((change / previous_close) * 100, 2)
        else:
            change = 'N/A'
            change_percent = 'N/A'
        
        # Financial metrics
        financials = {
            'roic': info.get('returnOnInvestmentCapital'),
            'roe': info.get('returnOnEquity'),
            'debt_to_equity': info.get('debtToEquity'),
            'current_ratio': info.get('currentRatio'),
            'profit_margins': info.get('profitMargins'),
            'free_cash_flow': info.get('freeCashflow'),
            'operating_margin': info.get('operatingMargins'),
            'ebitda_margin': info.get('ebitdaMargins')
        }
        
        # Growth metrics
        growth = {}
        try:
            financials_df = stock.financials
            if not financials_df.empty:
                revenue = financials_df.loc['Total Revenue']
                net_income = financials_df.loc['Net Income']
                
                if len(revenue) > 1:
                    revenue_growth = round(((revenue[0] - revenue[1]) / revenue[1]) * 100, 2)
                    growth['revenue_growth'] = revenue_growth
                
                if len(net_income) > 1:
                    net_income_growth = round(((net_income[0] - net_income[1]) / net_income[1]) * 100, 2)
                    growth['net_income_growth'] = net_income_growth
        except Exception:
            pass
        
        # Valuation metrics
        valuation = {
            'pe_ratio': info.get('trailingPE'),
            'peg_ratio': info.get('pegRatio'),
            'price_to_sales': info.get('priceToSalesTrailing12Months'),
            'price_to_book': info.get('priceToBook'),
            'enterprise_value': info.get('enterpriseValue'),
            'forward_pe': info.get('forwardPE'),
            'dividend_yield': info.get('dividendYield')
        }
        
        # Technical indicators
        technicals = {}
        try:
            hist = stock.history(period="1y")
            if not hist.empty:
                # Moving averages
                hist['50ma'] = hist['Close'].rolling(window=50).mean()
                hist['200ma'] = hist['Close'].rolling(window=200).mean()
                
                # RSI calculation
                delta = hist['Close'].diff()
                gain = delta.where(delta > 0, 0)
                loss = -delta.where(delta < 0, 0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
                # MACD
                exp12 = hist['Close'].ewm(span=12, adjust=False).mean()
                exp26 = hist['Close'].ewm(span=26, adjust=False).mean()
                macd = exp12 - exp26
                signal = macd.ewm(span=9, adjust=False).mean()
                
                technicals = {
                    '50ma': round(hist['50ma'].iloc[-1], 2),
                    '200ma': round(hist['200ma'].iloc[-1], 2),
                    'rsi': round(rsi.iloc[-1], 2) if not rsi.empty else None,
                    'macd': round(macd.iloc[-1], 2),
                    'signal': round(signal.iloc[-1], 2),
                    'histogram': round(macd.iloc[-1] - signal.iloc[-1], 2)
                }
        except Exception:
            pass
        
        # Ownership and governance
        ownership = {
            'institutional_holders': info.get('heldPercentInstitutions'),
            'insider_holders': info.get('heldPercentInsiders'),
            'shares_outstanding': info.get('sharesOutstanding'),
            'float_shares': info.get('floatShares')
        }
        
        # Analyst recommendations
        recommendations = {}
        try:
            rec_df = stock.recommendations
            if rec_df is not None and not rec_df.empty:
                latest_rec = rec_df.iloc[0]
                recommendations = {
                    'firm': latest_rec['Firm'],
                    'rating': latest_rec['To Grade'],
                    'action': latest_rec['Action'],
                    'date': latest_rec.name.strftime('%Y-%m-%d'),
                    'target_price': info.get('targetMeanPrice')
                }
        except Exception:
            pass
        
        # Get promoter holding for Indian stocks
        promoter_holding = None
        if '.NS' in ticker:
            try:
                nse_ticker = ticker.replace('.NS', '')
                nse_url = f"https://www.nseindia.com/api/quote-equity?symbol={nse_ticker}"
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                }
                response = requests.get(nse_url, headers=headers)
                if response.status_code == 200:
                    nse_data = response.json()
                    holding_data = nse_data.get('shareHoldingPattern', {})
                    promoter_holding = holding_data.get('promoterHolding', None)
            except:
                pass
        
        # Business model and competitive analysis
        business_model = {
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'summary': info.get('longBusinessSummary', ''),
            'website': info.get('website', ''),
            'full_time_employees': info.get('fullTimeEmployees', '')
        }
        
        # Risk analysis
        risk_analysis = {
            'beta': info.get('beta'),
            'volatility': technicals.get('rsi')  # Using RSI as volatility proxy
        }
        
        # Prepare response
        response_data = {
            "type": "stock",
            "name": name,
            "symbol": symbol,
            "current_price": current_price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "currency": currency,
            "financials": financials,
            "growth": growth,
            "valuation": valuation,
            "technicals": technicals,
            "ownership": ownership,
            "recommendations": recommendations,
            "business_model": business_model,
            "risk_analysis": risk_analysis,
            "promoter_holding": promoter_holding,
            "timestamp": updated_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Update cache
        data_cache['stocks'][ticker] = {
            'data': response_data,
            'timestamp': updated_time
        }
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Mutual fund analysis endpoint
@app.route("/api/mf/<scheme_code>", methods=["GET"])
def get_mutual_fund(scheme_code):
    try:
        # Check cache first
        if scheme_code in data_cache['mutual_funds']:
            cached_data = data_cache['mutual_funds'][scheme_code]
            cache_age = (datetime.now() - cached_data.get('nav_timestamp', datetime(1970,1,1))).total_seconds()
            if cache_age < CACHE_EXPIRY['mutual_funds'] and 'nav_data' in cached_data:
                return jsonify(cached_data['nav_data'])
        
        # Get fund metadata
        fund_data = data_cache['mutual_funds'].get(int(scheme_code), {})
        
        # Get NAV data
        nav_response = requests.get(f'https://api.mfapi.in/mf/{scheme_code}')
        if nav_response.status_code != 200:
            return jsonify({"error": "Fund data not found"}), 404
            
        nav_data = nav_response.json()
        nav_history = nav_data.get('data', [])
        
        # Process NAV data
        nav_values = []
        for entry in nav_history:
            try:
                date = datetime.strptime(entry['date'], '%d-%m-%Y')
                nav = float(entry['nav'])
                nav_values.append({'date': date, 'nav': nav})
            except (ValueError, KeyError):
                continue
        
        if not nav_values:
            return jsonify({"error": "No valid NAV data found"}), 400
            
        nav_df = pd.DataFrame(nav_values).sort_values('date')
        nav_df.set_index('date', inplace=True)
        
        # Calculate returns
        returns = {}
        periods = {
            '1m': 30,
            '3m': 90,
            '6m': 180,
            '1y': 365,
            '3y': 365*3,
            '5y': 365*5
        }
        
        latest_nav = nav_df['nav'].iloc[-1]
        for period, days in periods.items():
            if len(nav_df) > days:
                past_nav = nav_df['nav'].iloc[-days]
                returns[period] = round(((latest_nav - past_nav) / past_nav) * 100, 2)
        
        # Calculate volatility (standard deviation of monthly returns)
        monthly_returns = nav_df['nav'].resample('M').last().pct_change().dropna()
        volatility = round(monthly_returns.std() * 100, 2) if not monthly_returns.empty else 0
        
        # Calculate max drawdown
        rolling_max = nav_df['nav'].cummax()
        drawdown = (nav_df['nav'] - rolling_max) / rolling_max
        max_drawdown = round(drawdown.min() * 100, 2)
        
        # Calculate Sharpe ratio (simplified)
        risk_free_rate = 0.05  # 5% as risk-free rate
        sharpe_ratio = round((monthly_returns.mean() * 12 - risk_free_rate) / (monthly_returns.std() * np.sqrt(12)), 2) if not monthly_returns.empty else 0
        
        # Get fund details from Value Research (example - would need actual API)
        fund_details = {
            'expense_ratio': 0.85,  # Placeholder
            'fund_manager': 'Fund Manager Name',  # Placeholder
            'rating': 4,  # Placeholder
            'risk_level': 'Moderately High'
        }
        
        # Prepare response
        response_data = {
            "type": "mutual_fund",
            "scheme_code": scheme_code,
            "name": fund_data.get('name', ''),
            "category": fund_data.get('category', ''),
            "fund_type": fund_data.get('type', ''),
            "latest_nav": latest_nav,
            "returns": returns,
            "risk_metrics": {
                "volatility": volatility,
                "max_drawdown": max_drawdown,
                "sharpe_ratio": sharpe_ratio
            },
            "fund_details": fund_details,
            "as_of_date": nav_df.index[-1].strftime('%Y-%m-%d')
        }
        
        # Update cache
        if scheme_code in data_cache['mutual_funds']:
            data_cache['mutual_funds'][scheme_code]['nav_data'] = response_data
            data_cache['mutual_funds'][scheme_code]['nav_timestamp'] = datetime.now()
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Mutual fund search endpoint
@app.route("/api/mf/search", methods=["GET"])
def search_mutual_funds():
    query = request.args.get('query', '')
    if not query:
        return jsonify([])
    
    results = []
    for scheme_code, fund in data_cache['mutual_funds'].items():
        if re.search(query, fund['name'], re.IGNORECASE):
            results.append({
                'scheme_code': scheme_code,
                'name': fund['name'],
                'category': fund['category']
            })
    
    return jsonify(results[:10])  # Return top 10 results

# Crypto analysis endpoint
@app.route("/api/crypto/<symbol>", methods=["GET"])
def get_crypto(symbol):
    try:
        # Check cache first
        cache_key = f"{symbol}-USD"
        if cache_key in data_cache['crypto']:
            cached_data = data_cache['crypto'][cache_key]
            cache_age = (datetime.now() - cached_data['timestamp']).total_seconds()
            if cache_age < CACHE_EXPIRY['crypto']:
                return jsonify(cached_data['data'])
        
        crypto = yf.Ticker(f"{symbol}-USD")
        info = crypto.info
        updated_time = datetime.now()
        
        # Basic data
        name = info.get('name', symbol.upper())
        current_price = info.get('currentPrice') or info.get('regularMarketPrice')
        previous_close = info.get('previousClose') or info.get('regularMarketPreviousClose')
        
        # Calculate change
        if all(isinstance(x, (int, float)) for x in [current_price, previous_close]):
            change = round(current_price - previous_close, 2)
            change_percent = round((change / previous_close) * 100, 2)
        else:
            change = 'N/A'
            change_percent = 'N/A'
        
        # Market data
        market_data = {
            'market_cap': info.get('marketCap'),
            'volume_24h': info.get('volume24Hr'),
            'circulating_supply': info.get('circulatingSupply'),
            'max_supply': info.get('maxSupply'),
            'total_supply': info.get('totalSupply')
        }
        
        # Historical data for technical analysis
        technicals = {}
        try:
            hist = crypto.history(period="1y")
            if not hist.empty:
                # Moving averages
                hist['50ma'] = hist['Close'].rolling(window=50).mean()
                hist['200ma'] = hist['Close'].rolling(window=200).mean()
                
                # Volatility
                daily_returns = hist['Close'].pct_change().dropna()
                volatility = daily_returns.std() * np.sqrt(365) * 100  # Annualized volatility
                
                # RSI
                delta = hist['Close'].diff()
                gain = delta.where(delta > 0, 0)
                loss = -delta.where(delta < 0, 0)
                avg_gain = gain.rolling(window=14).mean()
                avg_loss = loss.rolling(window=14).mean()
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                
                technicals = {
                    '50ma': round(hist['50ma'].iloc[-1], 2),
                    '200ma': round(hist['200ma'].iloc[-1], 2),
                    'volatility': round(volatility, 2),
                    'rsi': round(rsi.iloc[-1], 2) if not rsi.empty else None
                }
        except Exception:
            pass
        
        # Prepare response
        response_data = {
            "type": "crypto",
            "name": name,
            "symbol": symbol.upper(),
            "current_price": current_price,
            "previous_close": previous_close,
            "change": change,
            "change_percent": change_percent,
            "market_data": market_data,
            "technicals": technicals,
            "timestamp": updated_time.strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # Update cache
        data_cache['crypto'][cache_key] = {
            'data': response_data,
            'timestamp': updated_time
        }
        
        return jsonify(response_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# SIP Calculator
@app.route("/api/sip/calculate", methods=["GET"])
def calculate_sip():
    try:
        monthly_investment = float(request.args.get('amount', 5000))
        years = int(request.args.get('years', 10))
        expected_return = float(request.args.get('return', 12))
        
        # Calculate future value
        monthly_rate = expected_return / 100 / 12
        months = years * 12
        future_value = monthly_investment * (((1 + monthly_rate) ** months - 1) / monthly_rate) * (1 + monthly_rate)
        
        # Calculate investment details
        total_investment = monthly_investment * months
        returns = future_value - total_investment
        
        return jsonify({
            "future_value": round(future_value, 2),
            "total_investment": total_investment,
            "returns": round(returns, 2),
            "months": months,
            "monthly_investment": monthly_investment,
            "expected_return": expected_return
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# SWP Calculator
@app.route("/api/swp/calculate", methods=["GET"])
def calculate_swp():
    try:
        principal = float(request.args.get('principal', 1000000))
        years = int(request.args.get('years', 10))
        withdrawal_rate = float(request.args.get('rate', 8))
        expected_return = float(request.args.get('return', 12))
        
        # Calculate monthly withdrawal
        monthly_rate = expected_return / 100 / 12
        months = years * 12
        monthly_withdrawal = principal * monthly_rate * (1 + monthly_rate) ** months / ((1 + monthly_rate) ** months - 1)
        
        # Calculate ending balance
        balance = principal
        monthly_growth = (1 + expected_return / 100) ** (1/12)
        for _ in range(months):
            balance = balance * monthly_growth - monthly_withdrawal
        
        return jsonify({
            "monthly_withdrawal": round(monthly_withdrawal, 2),
            "ending_balance": round(balance, 2),
            "total_withdrawn": round(monthly_withdrawal * months, 2),
            "months": months,
            "principal": principal,
            "expected_return": expected_return,
            "withdrawal_rate": withdrawal_rate
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Historical SIP Simulation
@app.route("/api/sip/simulate", methods=["GET"])
def simulate_sip():
    try:
        scheme_code = request.args.get('scheme_code', '120503')  # Default to a fund
        monthly_investment = float(request.args.get('amount', 5000))
        years = int(request.args.get('years', 5))
        
        # Get NAV history
        nav_response = requests.get(f'https://api.mfapi.in/mf/{scheme_code}')
        if nav_response.status_code != 200:
            return jsonify({"error": "Fund data not found"}), 404
        
        nav_data = nav_response.json().get('data', [])
        nav_values = []
        for entry in nav_data:
            try:
                date = datetime.strptime(entry['date'], '%d-%m-%Y')
                nav = float(entry['nav'])
                nav_values.append({'date': date, 'nav': nav})
            except:
                continue
        
        if not nav_values:
            return jsonify({"error": "No valid NAV data found"}), 400
            
        nav_df = pd.DataFrame(nav_values).sort_values('date')
        nav_df.set_index('date', inplace=True)
        
        # Get fund name
        fund_name = data_cache['mutual_funds'].get(int(scheme_code), {}).get('name', 'Unknown Fund')
        
        # Simulate SIP
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years*365)
        
        # Filter NAV data for the period
        period_nav = nav_df.loc[start_date:end_date]
        if period_nav.empty:
            return jsonify({"error": "Insufficient data for simulation"}), 400
        
        # Calculate units purchased each month
        investment_dates = pd.date_range(start=start_date, end=end_date, freq='MS')
        investments = []
        total_units = 0
        
        for date in investment_dates:
            # Find the closest NAV date
            try:
                nav_date = period_nav.index[period_nav.index >= date][0]
                nav_value = period_nav.loc[nav_date, 'nav']
                units = monthly_investment / nav_value
                total_units += units
                
                investments.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'nav': nav_value,
                    'units': units,
                    'amount': monthly_investment
                })
            except:
                continue
        
        # Calculate current value
        current_nav = period_nav.iloc[-1]['nav']
        current_value = total_units * current_nav
        total_invested = len(investments) * monthly_investment
        gain = current_value - total_invested
        gain_percent = (gain / total_invested) * 100
        
        return jsonify({
            "fund_name": fund_name,
            "scheme_code": scheme_code,
            "total_invested": round(total_invested, 2),
            "current_value": round(current_value, 2),
            "gain": round(gain, 2),
            "gain_percent": round(gain_percent, 2),
            "total_units": round(total_units, 4),
            "current_nav": round(current_nav, 4),
            "start_date": start_date.strftime('%Y-%m-%d'),
            "end_date": end_date.strftime('%Y-%m-%d'),
            "monthly_investment": monthly_investment,
            "investment_count": len(investments)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Top movers endpoint
@app.route("/api/topmovers", methods=["GET"])
def get_top_movers():
    try:
        # Check cache
        if data_cache['top_movers']['data'] and data_cache['top_movers']['last_updated']:
            cache_age = (datetime.now() - data_cache['top_movers']['last_updated']).total_seconds()
            if cache_age < CACHE_EXPIRY['top_movers']:
                return jsonify(data_cache['top_movers']['data'])
        
        # Top Indian stocks
        indian_tickers = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS', 
                         'KOTAKBANK.NS', 'HINDUNILVR.NS', 'AXISBANK.NS', 'SBIN.NS', 'BAJFINANCE.NS']
        
        movers = []
        for ticker in indian_tickers:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                current = info.get('currentPrice') or info.get('regularMarketPrice')
                previous = info.get('previousClose') or info.get('regularMarketPreviousClose')
                
                if current and previous:
                    change = current - previous
                    change_percent = (change / previous) * 100
                else:
                    change = 0
                    change_percent = 0
                    
                movers.append({
                    "symbol": ticker,
                    "name": info.get('shortName', ticker),
                    "price": current,
                    "change": round(change, 2),
                    "change_percent": round(change_percent, 2)
                })
                time.sleep(0.1)  # Rate limiting
            except:
                continue
        
        # Sort by percentage change
        movers.sort(key=lambda x: x['change_percent'], reverse=True)
        
        # Get top 5 gainers and losers
        top_gainers = movers[:5]
        top_losers = movers[-5:]
        
        # Update cache
        data_cache['top_movers']['data'] = {
            "gainers": top_gainers,
            "losers": top_losers
        }
        data_cache['top_movers']['last_updated'] = datetime.now()
        
        return jsonify(data_cache['top_movers']['data'])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Top mutual funds by category
@app.route("/api/topfunds/<category>", methods=["GET"])
def get_top_funds(category):
    try:
        # This would require a proper mutual fund ranking API
        # For demo, return some funds from cache
        funds = []
        for scheme_code, fund in data_cache['mutual_funds'].items():
            if category.lower() in fund['category'].lower():
                funds.append({
                    'scheme_code': scheme_code,
                    'name': fund['name'],
                    'category': fund['category']
                })
        
        return jsonify(funds[:5])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    load_mutual_fund_data()
    app.run(host="0.0.0.0", port=8000, threaded=True)
