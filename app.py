from flask import Flask, jsonify
from flask_cors import CORS
import yfinance as yf
from datetime import datetime

app = Flask(__name__)
CORS(app)

@app.route("/api/stock/<ticker>", methods=["GET"])
def get_stock(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        updated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
