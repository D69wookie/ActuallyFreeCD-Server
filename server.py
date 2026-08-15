from flask import Flask, jsonify

from drive_discovery import find_cd_drives
from musicbrainz import lookup_disc


app = Flask(__name__)

SERVER_VERSION = "0.4"


@app.route("/")
def home():
    return (
        f"ActuallyFreeCD Server "
        f"v{SERVER_VERSION}"
    )


@app.route("/api/status")
def status():
    return jsonify({
        "name": "ActuallyFreeCD Server",
        "version": SERVER_VERSION,
        "status": "running",
    })


@app.route("/api/drives")
def drives():
    try:
        discovered = find_cd_drives()

        return jsonify({
            "server": (
                "ActuallyFreeCD Server"
            ),
            "version": SERVER_VERSION,
            "drive_count": len(
                discovered
            ),
            "drives": discovered,
        })

    except Exception as exc:
        return jsonify({
            "server": (
                "ActuallyFreeCD Server"
            ),
            "version": SERVER_VERSION,
            "error": str(exc),
            "drives": [],
        }), 500


@app.route(
    "/api/drives/<drive_id>/metadata"
)
def drive_metadata(drive_id):
    try:
        discovered = find_cd_drives()

        drive = next(
            (
                item
                for item in discovered
                if item.get("id")
                == drive_id
            ),
            None,
        )

        if drive is None:
            return jsonify({
                "error": (
                    "Drive not found"
                ),
                "drive_id": drive_id,
            }), 404

        disc = drive.get(
            "disc",
            {},
        )

        if not disc.get("present"):
            return jsonify({
                "error": (
                    "No readable disc "
                    "is present"
                ),
                "drive_id": drive_id,
            }), 404

        if not disc.get("audio"):
            return jsonify({
                "error": (
                    "Disc is not an "
                    "audio CD"
                ),
                "drive_id": drive_id,
            }), 400

        metadata = lookup_disc(
            disc.get(
                "tracks",
                [],
            )
        )

        return jsonify({
            "server": (
                "ActuallyFreeCD Server"
            ),
            "version": SERVER_VERSION,
            "drive": {
                "id": drive.get("id"),
                "vendor": drive.get(
                    "vendor"
                ),
                "model": drive.get(
                    "model"
                ),
                "serial": drive.get(
                    "serial"
                ),
            },
            "metadata": metadata,
        })

    except Exception as exc:
        return jsonify({
            "error": str(exc),
            "drive_id": drive_id,
        }), 500


if __name__ == "__main__":
    print(
        f"ActuallyFreeCD Server "
        f"v{SERVER_VERSION}"
    )
    print("Listening on port 8080")

    app.run(
        host="0.0.0.0",
        port=8080,
    )