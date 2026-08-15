import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = (
    "ActuallyFreeCD/0.4 "
    "(wookiesoft+actuallyfreeCD@gmail.com)"
)

MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/discid/"

_last_request_time = 0.0


def calculate_disc_id(tracks):
    if not tracks:
        return None

    first_track = tracks[0]["number"]
    last_track = tracks[-1]["number"]

    offsets = {
        track["number"]: track["start_sector"] + 150
        for track in tracks
    }

    last = tracks[-1]

    leadout = (
        last["start_sector"]
        + last["sectors"]
        + 150
    )

    toc_string = (
        f"{first_track:02X}"
        f"{last_track:02X}"
        f"{leadout:08X}"
    )

    for track_number in range(1, 100):
        offset = offsets.get(track_number, 0)
        toc_string += f"{offset:08X}"

    digest = hashlib.sha1(
        toc_string.encode("ascii")
    ).digest()

    disc_id = base64.b64encode(
        digest
    ).decode("ascii")

    disc_id = (
        disc_id
        .replace("+", ".")
        .replace("/", "_")
        .replace("=", "-")
    )

    return {
        "disc_id": disc_id,
        "first_track": first_track,
        "last_track": last_track,
        "leadout": leadout,
        "offsets": [
            offsets[number]
            for number in range(
                first_track,
                last_track + 1
            )
        ],
    }


def build_toc(disc):
    values = [
        disc["first_track"],
        disc["last_track"],
        disc["leadout"],
    ]

    values.extend(disc["offsets"])

    return " ".join(
        str(value)
        for value in values
    )


def artist_credit_text(artist_credit):
    parts = []

    for credit in artist_credit or []:
        if isinstance(credit, str):
            parts.append(credit)
            continue

        parts.append(
            credit.get("name", "")
        )

        joinphrase = credit.get(
            "joinphrase"
        )

        if joinphrase:
            parts.append(joinphrase)

    return "".join(parts)


def _rate_limit():
    global _last_request_time

    now = time.monotonic()
    elapsed = now - _last_request_time

    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    _last_request_time = time.monotonic()


def _request_json(url):
    _rate_limit()

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def _medium_disc_ids(medium):
    disc_ids = []

    for disc in medium.get("discs", []):
        disc_id = disc.get("id")

        if disc_id:
            disc_ids.append(disc_id)

    return disc_ids


def _medium_matches_disc(
    medium,
    disc_id,
    physical_track_count,
):
    disc_ids = _medium_disc_ids(medium)

    if disc_id in disc_ids:
        return True, "exact_disc_id"

    track_count = medium.get(
        "track-count"
    )

    if (
        track_count is not None
        and track_count == physical_track_count
    ):
        return True, "track_count"

    return False, None


def _format_tracks(medium):
    tracks = []

    for track in medium.get(
        "tracks",
        [],
    ):
        recording = track.get(
            "recording",
            {},
        )

        artist = artist_credit_text(
            track.get(
                "artist-credit",
                recording.get(
                    "artist-credit",
                    [],
                ),
            )
        )

        tracks.append({
            "number": track.get("number"),
            "position": track.get(
                "position"
            ),
            "title": track.get(
                "title",
                recording.get(
                    "title",
                    "",
                ),
            ),
            "artist": artist,
            "recording_mbid": (
                recording.get("id")
            ),
            "length_ms": track.get(
                "length"
            ),
        })

    return tracks


def lookup_disc(tracks):
    disc = calculate_disc_id(tracks)

    if not disc:
        return {
            "status": "no_disc_id",
            "releases": [],
        }

    disc_id = disc["disc_id"]
    toc = build_toc(disc)

    params = urllib.parse.urlencode({
        "toc": toc,
        "inc": (
            "recordings+"
            "artist-credits+"
            "release-groups"
        ),
        "cdstubs": "no",
        "fmt": "json",
    })

    url = (
        MUSICBRAINZ_URL
        + urllib.parse.quote(disc_id)
        + "?"
        + params
    )

    try:
        result = _request_json(url)

    except urllib.error.HTTPError as exc:
        return {
            "status": "http_error",
            "http_status": exc.code,
            "disc_id": disc_id,
            "toc": toc,
            "releases": [],
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "disc_id": disc_id,
            "toc": toc,
            "releases": [],
        }

    physical_track_count = len(tracks)

    formatted_releases = []

    for release in result.get(
        "releases",
        [],
    ):
        media = release.get(
            "media",
            [],
        )

        matched_media = []

        for medium in media:
            matches, match_type = (
                _medium_matches_disc(
                    medium,
                    disc_id,
                    physical_track_count,
                )
            )

            if not matches:
                continue

            matched_media.append({
                "position": medium.get(
                    "position"
                ),
                "title": medium.get(
                    "title"
                ),
                "track_count": (
                    medium.get(
                        "track-count"
                    )
                ),
                "format": medium.get(
                    "format"
                ),
                "match_type": match_type,
                "disc_ids": (
                    _medium_disc_ids(
                        medium
                    )
                ),
                "tracks": (
                    _format_tracks(
                        medium
                    )
                ),
            })

        if not matched_media:
            continue

        release_group = release.get(
            "release-group",
            {},
        )

        formatted_releases.append({
            "release_mbid": release.get(
                "id"
            ),
            "release_group_mbid": (
                release_group.get("id")
            ),
            "title": release.get(
                "title"
            ),
            "artist": (
                artist_credit_text(
                    release.get(
                        "artist-credit",
                        [],
                    )
                )
            ),
            "date": release.get(
                "date"
            ),
            "country": release.get(
                "country"
            ),
            "status": release.get(
                "status"
            ),
            "barcode": release.get(
                "barcode"
            ),
            "medium_count": len(media),
            "matched_media": (
                matched_media
            ),
        })

    return {
        "status": (
            "matched"
            if formatted_releases
            else "no_match"
        ),
        "disc_id": disc_id,
        "toc": toc,
        "release_count": len(
            formatted_releases
        ),
        "releases": formatted_releases,
    }