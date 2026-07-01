"""Swing screener web server using Python stdlib only (no Flask required)."""

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

SCREENER_RESULTS = [
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "price": 487.21, "change": 12.43, "change_pct": 2.62, "volume": 42_800_000, "avg_volume": 38_500_000, "signal": "Bullish Breakout", "rsi": 58.3, "sector": "Technology"},
    {"symbol": "META", "name": "Meta Platforms Inc.", "price": 528.64, "change": -4.18, "change_pct": -0.78, "volume": 18_200_000, "avg_volume": 16_900_000, "signal": "Pullback to Support", "rsi": 44.7, "sector": "Communication Services"},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "price": 196.14, "change": 3.27, "change_pct": 1.69, "volume": 31_500_000, "avg_volume": 28_000_000, "signal": "Volume Surge", "rsi": 62.1, "sector": "Consumer Discretionary"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "price": 422.87, "change": 1.54, "change_pct": 0.37, "volume": 21_300_000, "avg_volume": 22_100_000, "signal": "Trend Continuation", "rsi": 55.9, "sector": "Technology"},
    {"symbol": "TSLA", "name": "Tesla Inc.", "price": 248.50, "change": -9.30, "change_pct": -3.61, "volume": 87_400_000, "avg_volume": 74_200_000, "signal": "Oversold Bounce", "rsi": 31.4, "sector": "Consumer Discretionary"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "price": 178.92, "change": 2.81, "change_pct": 1.60, "volume": 24_600_000, "avg_volume": 22_800_000, "signal": "Momentum Play", "rsi": 60.4, "sector": "Communication Services"},
]

STOCK_DETAILS = {
    "NVDA": {"description": "NVIDIA designs GPUs and system-on-chip units. It is a key player in AI accelerators, gaming, and data centers.", "market_cap": "1.20T", "pe_ratio": 68.4, "eps": 7.12, "week_52_high": 974.00, "week_52_low": 392.30, "dividend_yield": "0.03%", "beta": 1.67, "sma_50": 462.10, "sma_200": 580.42, "analysis": "Strong AI tailwind. Price above 50-day SMA. Volume confirming the move.", "chart_data": [420, 435, 448, 441, 458, 472, 465, 480, 487]},
    "META": {"description": "Meta operates Facebook, Instagram, and WhatsApp. Heavy investment in AI and the metaverse.", "market_cap": "1.35T", "pe_ratio": 27.1, "eps": 19.50, "week_52_high": 590.00, "week_52_low": 345.50, "dividend_yield": "0.36%", "beta": 1.23, "sma_50": 515.30, "sma_200": 487.60, "analysis": "Pulled back to 50-day SMA support. RSI indicates room to recover.", "chart_data": [545, 540, 535, 530, 528, 522, 518, 525, 529]},
    "AMZN": {"description": "Amazon is a global e-commerce and cloud company. AWS is the dominant cloud infrastructure provider.", "market_cap": "2.09T", "pe_ratio": 42.8, "eps": 4.59, "week_52_high": 215.90, "week_52_low": 151.60, "dividend_yield": "0.00%", "beta": 1.14, "sma_50": 188.40, "sma_200": 181.20, "analysis": "Volume surge on no news — institutional accumulation signal. Price above both SMAs.", "chart_data": [180, 183, 185, 184, 189, 192, 194, 193, 196]},
    "MSFT": {"description": "Microsoft develops software, services, and devices. Azure and AI Copilot are key growth drivers.", "market_cap": "3.14T", "pe_ratio": 36.2, "eps": 11.68, "week_52_high": 468.35, "week_52_low": 380.25, "dividend_yield": "0.67%", "beta": 0.89, "sma_50": 415.80, "sma_200": 408.50, "analysis": "Low beta, stable uptrend. Price holding above both SMAs.", "chart_data": [410, 412, 415, 418, 416, 420, 421, 422, 423]},
    "TSLA": {"description": "Tesla designs and sells electric vehicles, energy generation, and storage systems.", "market_cap": "795B", "pe_ratio": 61.3, "eps": 4.05, "week_52_high": 358.64, "week_52_low": 138.80, "dividend_yield": "0.00%", "beta": 2.31, "sma_50": 265.20, "sma_200": 231.40, "analysis": "RSI near oversold territory. High beta — watch for bounce from 52-week low zone.", "chart_data": [270, 268, 263, 255, 251, 248, 245, 247, 249]},
    "GOOGL": {"description": "Alphabet is Google's parent. Revenue is driven by Search, YouTube, and Google Cloud.", "market_cap": "2.22T", "pe_ratio": 22.1, "eps": 8.09, "week_52_high": 207.05, "week_52_low": 140.53, "dividend_yield": "0.00%", "beta": 1.05, "sma_50": 172.60, "sma_200": 165.80, "analysis": "Momentum building. Price above 50-day and 200-day SMA. Strong relative strength.", "chart_data": [168, 170, 172, 175, 174, 176, 177, 178, 179]},
}

SCREENER_BY_SYMBOL = {s["symbol"]: s for s in SCREENER_RESULTS}

MIME = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, path, mime):
        try:
            with open(path, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        p = self.path.split("?")[0]

        if p == "/" or p == "/index.html":
            self.serve_file("templates/index.html", "text/html")

        elif p == "/api/screener":
            self.send_json(SCREENER_RESULTS)

        elif m := re.fullmatch(r"/api/details/([A-Za-z]+)", p):
            symbol = m.group(1).upper()
            base = SCREENER_BY_SYMBOL.get(symbol)
            extra = STOCK_DETAILS.get(symbol)
            if base and extra:
                self.send_json({**base, **extra})
            else:
                self.send_json({"error": "Symbol not found"}, 404)

        elif p.startswith("/static/"):
            fname = p[len("/static/"):]
            ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
            mime = MIME.get(ext, "application/octet-stream")
            self.serve_file(f"static/{fname}", mime)

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    port = 5000
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Swing screener running at http://localhost:{port}")
    server.serve_forever()
