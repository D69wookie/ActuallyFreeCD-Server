import re
import shutil
import subprocess


def _blank_result(status, **extra):
    result = {
        "status": status,
        "source": "cdtext",
        "release_count": 0,
        "releases": [],
    }
    result.update(extra)
    return result


def _run_cd_info(device):
    executable = shutil.which("cd-info")

    if not executable:
        return None, "cd-info is not installed in the ActuallyFreeCD container"

    commands = [
        [
            executable,
            "--no-device-info",
            "--no-disc-mode",
            device,
        ],
        [
            executable,
            device,
        ],
    ]

    last_error = None

    for command in commands:
        try:
            process = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
                check=False,
            )
        except Exception as exc:
            last_error = str(exc)
            continue

        combined = "\n".join(
            part for part in (
                process.stdout,
                process.stderr,
            )
            if part
        )

        if "CD Analysis Report" in combined or "CD-TEXT" in combined:
            return combined, None

        last_error = (
            combined.strip()
            or f"cd-info exited with code {process.returncode}"
        )

    return None, last_error


def _parse_cd_info(text, physical_tracks):
    if not text:
        return None

    if "No CD-TEXT on Disc." in text:
        return None

    disc_fields = {}
    track_fields = {}
    current = None

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if line.startswith("CD-TEXT for Disc:"):
            current = ("disc", 0)
            continue

        match = re.match(
            r"CD-TEXT for Track\s+(\d+):",
            line,
            flags=re.IGNORECASE,
        )

        if match:
            number = int(match.group(1))
            current = ("track", number)
            track_fields.setdefault(number, {})
            continue

        field_match = re.match(
            r"([A-Z0-9_-]+)\s*:\s*(.*)$",
            line,
        )

        if not field_match or current is None:
            continue

        key = field_match.group(1).upper()
        value = field_match.group(2).strip()

        if not value:
            continue

        if current[0] == "disc":
            disc_fields[key] = value
        else:
            track_fields.setdefault(
                current[1], {}
            )[key] = value

    album = disc_fields.get("TITLE", "")
    album_artist = disc_fields.get("PERFORMER", "")

    formatted_tracks = []

    for physical in physical_tracks:
        number = int(physical.get("number", 0))
        fields = track_fields.get(number, {})

        title = fields.get("TITLE", "")
        artist = fields.get("PERFORMER", "") or album_artist

        formatted_tracks.append({
            "number": str(number),
            "position": number,
            "title": title or f"Track {number:02d}",
            "artist": artist,
            "recording_mbid": None,
            "length_ms": None,
        })

    has_useful_text = bool(
        album
        or album_artist
        or any(
            item.get("title")
            and not item["title"].startswith("Track ")
            for item in formatted_tracks
        )
        or any(item.get("artist") for item in formatted_tracks)
    )

    if not has_useful_text:
        return None

    return {
        "album": album,
        "album_artist": album_artist,
        "tracks": formatted_tracks,
        "raw_disc_fields": disc_fields,
        "raw_track_fields": track_fields,
    }


def lookup_cdtext(device, tracks):
    if not device:
        return _blank_result(
            "error",
            error="Drive device path is unavailable",
        )

    output, error = _run_cd_info(device)

    if output is None:
        return _blank_result(
            "unavailable",
            error=error,
        )

    parsed = _parse_cd_info(
        output,
        tracks or [],
    )

    if not parsed:
        return _blank_result(
            "no_cdtext",
        )

    album = parsed["album"]
    album_artist = parsed["album_artist"]

    medium = {
        "position": 1,
        "title": None,
        "track_count": len(tracks or []),
        "format": "CD",
        "match_type": "cdtext",
        "disc_ids": [],
        "tracks": parsed["tracks"],
    }

    release = {
        "release_mbid": None,
        "release_group_mbid": None,
        "title": album,
        "artist": album_artist,
        "date": None,
        "country": None,
        "status": None,
        "barcode": None,
        "medium_count": 1,
        "matched_media": [medium],
        "metadata_source": "cdtext",
    }

    return {
        "status": "matched",
        "source": "cdtext",
        "release_count": 1,
        "releases": [release],
    }
