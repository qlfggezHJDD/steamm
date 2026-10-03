"""
Steam Dead Ranker — Web Service edition
cron-job.org ping /run → script se lance → résultats sur Discord
"""

import threading
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/run":
            # Lance le scorer dans un thread séparé pour ne pas bloquer
            t = threading.Thread(target=lambda: subprocess.run(
                [sys.executable, "scorer.py"], capture_output=False
            ))
            t.daemon = True
            t.start()
            self._respond(200, "OK — scorer started")

        elif self.path == "/health":
            self._respond(200, "OK")

        else:
            self._respond(404, "Not found")

    def _respond(self, code, msg):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg.encode())

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

if __name__ == "__main__":
    port = 10000  # port par défaut Render
    print(f"Server running on port {port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
