"""Swing screener web server — serves live Robinhood scan data from data/live_scan.json."""

import json
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

DATA_FILE = os.path.join(os.path.dirname(__file__), "data", "live_scan.json")
SCAN_ID = "b7fb4961-de0b-4eed-b828-57084745e2da"

MIME = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
}


def load_data():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"meta": {}, "stocks": []}


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

        if p in ("/", "/index.html"):
            self.serve_file("templates/index.html", "text/html")

        elif p == "/api/screener":
            data = load_data()
            self.send_json({
                "stocks": data["stocks"],
                "meta": data.get("meta", {}),
                "last_updated": os.path.getmtime(DATA_FILE)
                    if os.path.exists(DATA_FILE) else None,
            })

        elif m := re.fullmatch(r"/api/details/([A-Za-z.]+)", p):
            symbol = m.group(1).upper()
            data = load_data()
            stock = next((s for s in data["stocks"] if s["symbol"] == symbol), None)
            if stock:
                self.send_json(stock)
            else:
                self.send_json({"error": f"{symbol} not in current scan results"}, 404)

        elif p == "/api/meta":
            data = load_data()
            mtime = os.path.getmtime(DATA_FILE) if os.path.exists(DATA_FILE) else None
            self.send_json({**data.get("meta", {}), "last_updated": mtime})

        elif p.startswith("/static/"):
            fname = p[len("/static/"):]
            ext = "." + fname.rsplit(".", 1)[-1] if "." in fname else ""
            self.serve_file(f"static/{fname}", MIME.get(ext, "application/octet-stream"))

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    port = 5000
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Swing screener running at http://localhost:{port}")
    print(f"Data file: {DATA_FILE}")
    server.serve_forever()
