import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from app.adapters.generic import GenericRESTAdapter


class ERPHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict]] = []

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        self.requests.append(("GET", path, {}))
        payload = {
            "/v1/products/Widget%20Pro/bom": {"bom": [{"material": "Steel", "quantity": 2}]},
            "/v1/materials/Copper/stock": {"available_qty": 12},
        }.get(path, {"suppliers": []})
        self._send(payload)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(("POST", urlparse(self.path).path, payload))
        self._send({"status": "created", **payload})

    def _send(self, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def test_generic_adapter_uses_yaml_mapping_against_http_server() -> None:
    ERPHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ERPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = Path(__file__).parents[1] / "app" / "adapters" / "mappings" / "example.yaml"
        adapter = GenericRESTAdapter(config_path=str(config), base_url=f"http://127.0.0.1:{server.server_port}")

        assert adapter.get_bom("Widget Pro") == [{"material": "Steel", "quantity": 2}]
        assert adapter.get_stock("Copper") == 12
        assert adapter.create_purchase_order("run-1", "Apex", "Copper", 4, 8.1)["status"] == "created"
        assert ("POST", "/v1/purchase-orders", {
            "run_id": "run-1",
            "supplier_name": "Apex",
            "material_name": "Copper",
            "quantity": 4,
            "unit_price": 8.1,
        }) in ERPHandler.requests
    finally:
        server.shutdown()
        thread.join(timeout=5)
