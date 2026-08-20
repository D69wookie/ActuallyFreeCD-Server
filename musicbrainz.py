import base64
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = (
    "ActuallyFreeCD/0.7f "
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
    leadout = last["start_sector"] + last["sectors"] + 150

    toc_string = (
        f"{first_track:02X}"
        f"{last_track:02X}"
        f"{leadout:08X}"
    )

    for track_number in range(1, 100):
        toc_string += f"{offsets.get(track_number, 0):08X}"

    digest = hashlib.sha1(toc_string.encode("ascii")).digest()
    disc_id = base64.b64encode(digest).decode("ascii")
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
            for number in range(first_track, last_track + 1)
        ],
    }


def build_toc(disc):
    values = [
        disc["first_track"],
        disc["last_track"],
        disc["leadout"],
    ]
    values.extend(disc["offsets"])
    return " ".join(str(value) for value in values)


def artist_credit_text(artist_credit):
    parts = []

    for credit in artist_credit or []:
        if isinstance(credit, str):
            parts.append(credit)
            continue

        name = credit.get("name", "")
        if not name:
            name = (credit.get("artist") or {}).get("name", "")

        parts.append(name)
        parts.append(credit.get("joinphrase", ""))

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

    mb_request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(mb_request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_tracks(medium):
    tracks = []

    for track in medium.get("tracks", []):
        recording = track.get("recording") or {}
        artist = artist_credit_text(
            track.get("artist-credit")
            or recording.get("artist-credit")
            or []
        )

        tracks.append({
            "number": track.get("number"),
            "position": track.get("position"),
            "title": track.get("title") or recording.get("title", ""),
            "artist": artist,
            "recording_mbid": recording.get("id"),
            "length_ms": track.get("length") or recording.get("length"),
        })

    return tracks


def _physical_track_length_ms(track):
    # Audio CD sectors are 1/75 second.  Use the physical TOC, just as the
    # Windows build compares CdDiscInfo track durations against MusicBrainz.
    sectors = track.get("sectors")
    if sectors is None:
        return None

    try:
        return float(sectors) * 1000.0 / 75.0
    except (TypeError, ValueError):
        return None


def _medium_duration_score(medium, physical_tracks):
    mb_tracks = medium.get("tracks") or []

    if len(mb_tracks) != len(physical_tracks):
        return None

    total_difference_ms = 0.0

    for physical, mb_track in zip(physical_tracks, mb_tracks):
        recording = mb_track.get("recording") or {}
        mb_length = mb_track.get("length") or recording.get("length")
        physical_length = _physical_track_length_ms(physical)

        try:
            mb_length = float(mb_length) if mb_length is not None else None
        except (TypeError, ValueError):
            mb_length = None

        # Mirror the Windows implementation: missing MusicBrainz duration
        # data is allowed, but penalised so a measurable candidate wins.
        if mb_length is None or mb_length <= 0 or physical_length is None:
            total_difference_ms += 60000.0
        else:
            total_difference_ms += abs(physical_length - mb_length)

    return total_difference_ms


def _best_matching_medium(media, physical_tracks):
    expected_track_count = len(physical_tracks)
    best_medium = None
    best_score = None

    for medium_index, medium in enumerate(media, start=1):
        track_count = medium.get("track-count")

        try:
            track_count = int(track_count)
        except (TypeError, ValueError):
            track_count = len(medium.get("tracks") or [])

        if track_count != expected_track_count:
            continue

        score = _medium_duration_score(medium, physical_tracks)
        if score is None:
            continue

        if best_score is None or score < best_score:
            best_score = score
            best_medium = medium
            best_medium["_actuallyfreecd_position"] = (
                medium.get("position") or medium_index
            )

    return best_medium, best_score


def _best_genre(release):
    best_name = ""
    best_count = -1

    for genre in release.get("genres") or []:
        name = genre.get("name", "")
        try:
            count = int(genre.get("count", 0))
        except (TypeError, ValueError):
            count = 0

        if name and count > best_count:
            best_name = name
            best_count = count

    return best_name


def _first_label(release):
    for info in release.get("label-info") or []:
        label = (info.get("label") or {}).get("name", "")
        catalogue_number = info.get("catalog-number", "")
        if label or catalogue_number:
            return label, catalogue_number
    return "", ""


def lookup_disc(tracks):
    disc = calculate_disc_id(tracks)

    if not disc:
        return {
            "status": "no_disc_id",
            "source": "musicbrainz",
            "releases": [],
        }

    disc_id = disc["disc_id"]
    toc = build_toc(disc)

    # Port of the known-working Windows MusicBrainzService strategy:
    # identify by the physical TOC using discid/- rather than requiring an
    # existing MusicBrainz Disc ID association, then choose the correct medium
    # by comparing physical track durations.
    params = urllib.parse.urlencode({
        "toc": toc,
        "inc": (
            "recordings+"
            "artist-credits+"
            "genres+"
            "labels+"
            "release-groups"
        ),
        "cdstubs": "no",
        "fmt": "json",
    })

    url = MUSICBRAINZ_URL + "-?" + params

    try:
        result = _request_json(url)

    except urllib.error.HTTPError as exc:
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""

        return {
            "status": "http_error",
            "source": "musicbrainz",
            "http_status": exc.code,
            "error": error_body,
            "disc_id": disc_id,
            "toc": toc,
            "releases": [],
        }

    except Exception as exc:
        return {
            "status": "error",
            "source": "musicbrainz",
            "error": str(exc),
            "disc_id": disc_id,
            "toc": toc,
            "releases": [],
        }

    formatted_releases = []

    for release in result.get("releases", []):
        media = release.get("media") or []
        medium, score = _best_matching_medium(media, tracks)

        if medium is None:
            continue

        formatted_tracks = _format_tracks(medium)
        if len(formatted_tracks) != len(tracks):
            continue

        release_group = release.get("release-group") or {}
        label, catalogue_number = _first_label(release)
        position = medium.get("_actuallyfreecd_position", 1)

        formatted_releases.append({
            "release_mbid": release.get("id"),
            "release_group_mbid": release_group.get("id"),
            "title": release.get("title"),
            "artist": artist_credit_text(release.get("artist-credit") or []),
            "date": release.get("date"),
            "country": release.get("country"),
            "status": release.get("status"),
            "barcode": release.get("barcode"),
            "disambiguation": release.get("disambiguation", ""),
            "label": label,
            "catalogue_number": catalogue_number,
            "genre": _best_genre(release),
            "medium_count": len(media),
            "matched_media": [{
                "position": position,
                "title": medium.get("title"),
                "track_count": medium.get("track-count"),
                "format": medium.get("format"),
                "match_type": "track_duration",
                "duration_score_ms": round(score, 3),
                "tracks": formatted_tracks,
            }],
        })

    formatted_releases.sort(
        key=lambda item: (
            item.get("artist") or "",
            item.get("title") or "",
            item.get("date") or "",
            item.get("country") or "",
        )
    )

    return {
        "status": "matched" if formatted_releases else "no_match",
        "source": "musicbrainz",
        "disc_id": disc_id,
        "toc": toc,
        "release_count": len(formatted_releases),
        "releases": formatted_releases,
    }
