from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
from datetime import datetime
import requests

app = Flask(__name__)
CORS(app)

# Stock endpoint
@app.route("/api/stock/<ticker>", methods=["GET"])
def get_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        updated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extract data
        name = info.get('longName', ticker.upper())
        symbol = ticker.upper()
        currentPrice = info.get('currentPrice') or info.get('regularMarketPrice')
        previousClose = info.get('previousClose') or info.get('regularMarketPreviousClose')
        open_price = info.get('open') or info.get('regularMarketOpen')
        high = info.get('dayHigh') or info.get('regularMarketDayHigh')
        low = info.get('dayLow') or info.get('regularMarketDayLow')
        volume = info.get('volume') or info.get('regularMarketVolume')
        currency = info.get('currency', 'N/A')
        exchangeName = info.get('exchange', 'N/A')

        if isinstance(currentPrice, (int, float)) and isinstance(previousClose, (int, float)):
            change = currentPrice - previousClose
            changePercent = (change / previousClose) * 100
        else:
            change = 'N/A'
            changePercent = 'N/A'

        return jsonify({
            "name": name,
            "symbol": symbol,
            "currentPrice": currentPrice,
            "previousClose": previousClose,
            "change": change,
            "changePercent": changePercent,
            "currency": currency,
            "exchangeName": exchangeName,
            "open": open_price,
            "high": high,
            "low": low,
            "volume": volume,
            "timestamp": updated_time
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Crypto endpoint
@app.route("/api/crypto", methods=["GET"])
def get_crypto():
    try:
        cryptos = [
            {"symbol": "BTC", "name": "Bitcoin"},
            {"symbol": "ETH", "name": "Ethereum"},
            {"symbol": "BNB", "name": "Binance Coin"},
            {"symbol": "SOL", "name": "Solana"},
            {"symbol": "XRP", "name": "Ripple"}
        ]
        
        for crypto in cryptos:
            ticker = f"{crypto['symbol']}-USD"
            data = yf.Ticker(ticker).history(period="1d")
            
            if not data.empty:
                crypto["price"] = data['Close'].iloc[-1]
                crypto["change"] = ((data['Close'].iloc[-1] - data['Open'].iloc[-1]) / data['Open'].iloc[-1]) * 100
            else:
                crypto["price"] = 0
                crypto["change"] = 0
        
        return jsonify(cryptos)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
