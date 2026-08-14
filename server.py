from flask import Flask, jsonify
from drive_discovery import find_cd_drives

app = Flask(__name__)

SERVER_VERSION = "0.3"


@app.route("/")
def home():
    return f"ActuallyFreeCD Server v{SERVER_VERSION}"


@app.route("/api/status")
def status():
    return jsonify({
        "name": "ActuallyFreeCD Server",
        "version": SERVER_VERSION,
        "status": "running"
    })


@app.route("/api/drives")
def drives():
    try:
        discovered_drives = find_cd_drives()

        return jsonify({
            "server": "ActuallyFreeCD Server",
            "version": SERVER_VERSION,
            "drive_count": len(discovered_drives),
            "drives": discovered_drives
        })

    except Exception as exc:
        return jsonify({
            "server": "ActuallyFreeCD Server",
            "version": SERVER_VERSION,
            "error": str(exc),
            "drives": []
        }), 500


if __name__ == "__main__":
    print(f"ActuallyFreeCD Server v{SERVER_VERSION}")
    print("Listening on port 8080")

    app.run(
        host="0.0.0.0",
        port=8080
    )