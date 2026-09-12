import json
import os
import re
import subprocess
import threading
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from pathlib import Path

from flask import Flask
from flask import Response
from flask import jsonify
from flask import render_template
from flask import request

import accuraterip
import ripper

from drive_discovery import find_cd_drives
from cdtext import lookup_cdtext
from musicbrainz import USER_AGENT
from musicbrainz import lookup_disc


app = Flask(__name__)

SERVER_VERSION = "1.0.2"

MUSIC_ROOT = Path(
    os.environ.get(
        "MUSIC_ROOT",
        "/music",
    )
)

SETTINGS_ROOT = (
    MUSIC_ROOT
    / ".actuallyfreecd"
)

DRIVE_SETTINGS_FILE = (
    SETTINGS_ROOT
    / "drive_settings.json"
)

DEFAULT_READ_OFFSET_SAMPLES = 0

ARTWORK_ROOT = (
    SETTINGS_ROOT
    / "artwork"
)

MAX_ARTWORK_BYTES = 10 * 1024 * 1024

ALLOWED_ARTWORK_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


def _optional_id_from_env(
    name
):

    value = str(
        os.environ.get(
            name,
            "",
        )
        or ""
    ).strip()

    if not value:

        return None

    try:

        number = int(
            value,
            10,
        )

    except ValueError as exc:

        raise RuntimeError(
            f"{name} must be a numeric UID/GID"
        ) from exc

    if number < 0:

        raise RuntimeError(
            f"{name} must be zero or greater"
        )

    return number


def _mode_from_env(
    name,
    default
):

    value = str(
        os.environ.get(
            name,
            default,
        )
        or default
    ).strip().lower()

    if value.startswith(
        "0o"
    ):

        value = value[2:]

    try:

        mode = int(
            value,
            8,
        )

    except ValueError as exc:

        raise RuntimeError(
            f"{name} must be an octal mode such as 0775"
        ) from exc

    if not (
        0 <= mode <= 0o7777
    ):

        raise RuntimeError(
            f"{name} must be between 0000 and 7777"
        )

    return mode


OUTPUT_UID = (
    _optional_id_from_env(
        "AFCD_OUTPUT_UID"
    )
)

OUTPUT_GID = (
    _optional_id_from_env(
        "AFCD_OUTPUT_GID"
    )
)

OUTPUT_DIR_MODE = (
    _mode_from_env(
        "AFCD_DIR_MODE",
        "0775",
    )
)

OUTPUT_FILE_MODE = (
    _mode_from_env(
        "AFCD_FILE_MODE",
        "0664",
    )
)

# When a shared output group is configured, setgid on directories
# keeps newly-created content associated with that same group.
EFFECTIVE_DIR_MODE = (
    OUTPUT_DIR_MODE
    | (
        0o2000
        if OUTPUT_GID is not None
        else 0
    )
)



# ============================================================
# MUSIC DESTINATION VALIDATION
# ============================================================

def get_music_root_status():

    status = {
        "path":
            str(
                MUSIC_ROOT
            ),

        "exists":
            False,

        "is_directory":
            False,

        "writable":
            False,

        "error":
            None,
    }

    try:

        MUSIC_ROOT.mkdir(
            parents=True,
            exist_ok=True,
        )

        status[
            "exists"
        ] = MUSIC_ROOT.exists()

        status[
            "is_directory"
        ] = MUSIC_ROOT.is_dir()

        if not status[
            "is_directory"
        ]:

            status[
                "error"
            ] = (
                "Configured music destination "
                "is not a directory."
            )

            return status

        probe = (
            MUSIC_ROOT
            / (
                ".actuallyfreecd-"
                "write-test"
            )
        )

        try:

            with probe.open(
                "w",
                encoding="utf-8",
            ) as file:

                file.write(
                    "ActuallyFreeCD write test\n"
                )

            probe.unlink()

            status[
                "writable"
            ] = True

        except Exception as exc:

            status[
                "error"
            ] = (
                "Music destination is not "
                "writable: "
                f"{exc}"
            )

    except Exception as exc:

        status[
            "error"
        ] = str(
            exc
        )

    return status


def require_writable_music_root():

    status = (
        get_music_root_status()
    )

    if not status.get(
        "writable"
    ):

        raise RuntimeError(
            status.get(
                "error"
            )
            or (
                "Music destination is "
                "not writable."
            )
        )

    return status


# ============================================================
# JOB STORAGE
# ============================================================

jobs = {}

jobs_lock = threading.Lock()

last_rip_job_id = None


# ============================================================

ACCURATERIP_DRIVE_OFFSETS_URL = (
    "https://www.accuraterip.com/driveoffsets.htm"
)


def _normalise_drive_name(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().lower(),
    )


def lookup_accuraterip_drive_offset(drive):
    vendor = str(drive.get("vendor", "") or "").strip()
    model = str(drive.get("model", "") or "").strip()

    if not model:
        return {
            "available": False,
            "found": False,
            "offset": None,
            "source": "accuraterip",
            "error": "Drive model is unavailable.",
        }

    request = urllib.request.Request(
        ACCURATERIP_DRIVE_OFFSETS_URL,
        headers={"User-Agent": USER_AGENT},
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=8,
        ) as response:
            raw = response.read(2 * 1024 * 1024)

        page = raw.decode(
            "utf-8",
            errors="replace",
        )

        page = re.sub(
            r"(?is)<script.*?</script>",
            " ",
            page,
        )

        page = re.sub(
            r"(?is)<style.*?</style>",
            " ",
            page,
        )

        import html as html_module

        vendor_n = _normalise_drive_name(
            vendor
        )

        model_n = _normalise_drive_name(
            model
        )

        rows = []

        # Parse whole HTML table rows before stripping tags. AccurateRip
        # puts cells on separate source lines, so line-based parsing can
        # find the model but lose the offset in the next <td>.
        table_rows = re.findall(
            r"(?is)<tr\b[^>]*>(.*?)</tr\s*>",
            page,
        )

        for row_html in table_rows:

            cells = re.findall(
                r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]\s*>",
                row_html,
            )

            cell_texts = []

            for cell in cells:

                text = re.sub(
                    r"(?i)<br\s*/?>",
                    " ",
                    cell,
                )

                text = re.sub(
                    r"(?s)<[^>]+>",
                    " ",
                    text,
                )

                text = html_module.unescape(
                    text
                )

                text = re.sub(
                    r"\s+",
                    " ",
                    text,
                ).strip()

                cell_texts.append(
                    text
                )

            if cell_texts:

                line = " | ".join(
                    cell_texts
                )

            else:

                line = re.sub(
                    r"(?s)<[^>]+>",
                    " ",
                    row_html,
                )

                line = html_module.unescape(
                    line
                )

                line = re.sub(
                    r"\s+",
                    " ",
                    line,
                ).strip()

            if not line:
                continue

            line_n = _normalise_drive_name(
                line
            )

            if model_n not in line_n:
                continue

            model_pos = line_n.find(
                model_n
            )

            offset_search_text = (
                line[
                    model_pos
                    + len(model)
                    :
                ]
                if model_pos >= 0
                else ""
            )

            offset_match = re.search(
                r"(?<!\d)([+-]\d+)(?!\d)",
                offset_search_text,
            )

            rows.append({
                "line": line,
                "vendor_match": bool(
                    vendor_n
                    and vendor_n in line_n
                ),
                "purged": "purged" in line_n,
                "offset": (
                    int(
                        offset_match.group(1)
                    )
                    if offset_match
                    else None
                ),
            })

        if not rows:
            return {
                "available": True,
                "found": False,
                "offset": None,
                "source": "accuraterip",
                "error": None,
            }

        exact = [
            row for row in rows
            if row["vendor_match"]
        ]
        candidates = exact or rows

        valid = [
            row for row in candidates
            if (
                not row["purged"]
                and row["offset"] is not None
            )
        ]

        if not valid:
            return {
                "available": True,
                "found": False,
                "offset": None,
                "source": "accuraterip",
                "purged": any(
                    row["purged"]
                    for row in candidates
                ),
                "matched_row": candidates[0]["line"],
                "error": (
                    "Drive is marked Purged in AccurateRip."
                    if any(
                        row["purged"]
                        for row in candidates
                    )
                    else None
                ),
            }

        offsets = {
            row["offset"]
            for row in valid
        }

        if len(offsets) != 1:
            return {
                "available": True,
                "found": False,
                "offset": None,
                "source": "accuraterip",
                "ambiguous": True,
                "matched_rows": [
                    row["line"]
                    for row in valid
                ],
                "error": (
                    "Multiple AccurateRip offsets "
                    "matched this drive."
                ),
            }

        best = valid[0]

        return {
            "available": True,
            "found": True,
            "offset": best["offset"],
            "source": "accuraterip",
            "purged": False,
            "matched_row": best["line"],
            "error": None,
        }

    except Exception as exc:
        return {
            "available": False,
            "found": False,
            "offset": None,
            "source": "accuraterip",
            "error": str(exc),
        }


def initialise_drive_settings(drive_id, drive):
    with drive_settings_lock:
        settings = load_drive_settings_file()
        key = str(drive_id)

        if key in settings:
            return None

        lookup = lookup_accuraterip_drive_offset(drive)

        offset = (
            int(lookup["offset"])
            if (
                lookup.get("found")
                and lookup.get("offset") is not None
            )
            else DEFAULT_READ_OFFSET_SAMPLES
        )

        settings[key] = {
            "read_offset_samples": offset,
            "offset_source": (
                "accuraterip"
                if lookup.get("found")
                else "default"
            ),
            "offset_lookup": lookup,
        }

        save_drive_settings_file(settings)
        return lookup


# DRIVE SETTINGS STORAGE
# ============================================================

drive_settings_lock = (
    threading.Lock()
)


def load_drive_settings_file():

    try:

        if not DRIVE_SETTINGS_FILE.exists():

            return {}

        with DRIVE_SETTINGS_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(
                file
            )

        if not isinstance(
            data,
            dict,
        ):

            return {}

        return data

    except Exception as exc:

        print(
            "Unable to read drive settings: "
            f"{exc}"
        )

        return {}


def save_drive_settings_file(
    settings
):

    SETTINGS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_path = (
        DRIVE_SETTINGS_FILE
        .with_suffix(
            ".json.tmp"
        )
    )

    with temp_path.open(
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            settings,
            file,
            indent=2,
            sort_keys=True,
        )

        file.write(
            "\n"
        )

    temp_path.replace(
        DRIVE_SETTINGS_FILE
    )


def get_drive_settings(
    drive_id
):

    with drive_settings_lock:

        settings = (
            load_drive_settings_file()
        )

        entry = settings.get(
            str(drive_id),
            {},
        )

        try:

            offset = int(
                entry.get(
                    "read_offset_samples",
                    DEFAULT_READ_OFFSET_SAMPLES,
                )
            )

        except Exception:

            offset = (
                DEFAULT_READ_OFFSET_SAMPLES
            )

        return {
            "read_offset_samples":
                offset,

            "saved":
                str(drive_id)
                in settings,

            "offset_source":
                entry.get(
                    "offset_source",
                    (
                        "saved"
                        if str(drive_id) in settings
                        else "default"
                    ),
                ),

            "offset_lookup":
                entry.get(
                    "offset_lookup"
                ),
        }


def set_drive_settings(
    drive_id,
    read_offset_samples,
):

    read_offset_samples = int(
        read_offset_samples
    )

    if not (
        -5000
        <= read_offset_samples
        <= 5000
    ):

        raise ValueError(
            "Read offset must be between "
            "-5000 and +5000 samples."
        )

    with drive_settings_lock:

        settings = (
            load_drive_settings_file()
        )

        existing = settings.get(
            str(drive_id),
            {},
        )

        if not isinstance(
            existing,
            dict,
        ):

            existing = {}

        existing[
            "read_offset_samples"
        ] = read_offset_samples

        existing[
            "offset_source"
        ] = "manual"

        existing[
            "offset_lookup"
        ] = None

        settings[
            str(drive_id)
        ] = existing

        save_drive_settings_file(
            settings
        )

    return {
        "read_offset_samples":
            read_offset_samples,

        "saved":
            True,

        "offset_source":
            "manual",

        "offset_lookup":
            None,
    }


# ============================================================
# PUBLIC JOB DATA
# ============================================================

def public_job(
    job
):

    return {
        "id":
            job["id"],

        "drive_id":
            job["drive_id"],

        "status":
            job["status"],

        "stage":
            job["stage"],

        "progress":
            round(
                job["progress"],
                1,
            ),

        "current_track":
            job["current_track"],

        "completed_tracks":
            job["completed_tracks"],

        "total_tracks":
            job["total_tracks"],

        "output_folder":
            job["output_folder"],

        "message":
            job["message"],

        "error":
            job["error"],

        "tracks":
            job["tracks"],

        "rip_mode":
            job["rip_mode"],

        "output_format":
            job.get(
                "output_format",
                "FLAC",
            ),

        "mp3_quality":
            job.get(
                "mp3_quality",
                "V0 (Highest VBR)",
            ),

        "read_offset_samples":
            job[
                "read_offset_samples"
            ],

        "accuraterip":
            job.get(
                "accuraterip"
            ),

        "log_file":
            job.get(
                "log_file"
            ),

        "eject_after_rip":
            bool(
                job.get(
                    "eject_after_rip",
                    False,
                )
            ),

        "eject_status":
            job.get(
                "eject_status"
            ),

        "eject_error":
            job.get(
                "eject_error"
            ),
    }


# ============================================================
# DRIVE HELPERS
# ============================================================

def find_drive(
    drive_id
):

    discovered = (
        find_cd_drives()
    )

    return next(
        (
            item
            for item in discovered
            if item.get("id")
            == drive_id
        ),
        None,
    )



# ============================================================
# OUTPUT OWNERSHIP / PERMISSIONS
# ============================================================

def _apply_output_owner(
    path
):

    if (
        OUTPUT_UID is None
        and OUTPUT_GID is None
    ):

        return

    uid = (
        OUTPUT_UID
        if OUTPUT_UID is not None
        else -1
    )

    gid = (
        OUTPUT_GID
        if OUTPUT_GID is not None
        else -1
    )

    os.chown(
        path,
        uid,
        gid,
    )


def apply_output_directory_permissions(
    directory
):

    directory = Path(
        directory
    )

    try:

        root = MUSIC_ROOT.resolve()
        current = directory.resolve()

        paths = []

        while (
            current != root
            and root in current.parents
        ):

            paths.append(
                current
            )

            current = (
                current.parent
            )

        for path in reversed(
            paths
        ):

            _apply_output_owner(
                path
            )

            os.chmod(
                path,
                EFFECTIVE_DIR_MODE,
            )

    except Exception as exc:

        print(
            "Unable to apply output directory "
            f"permissions to {directory}: {exc}"
        )


def apply_output_file_permissions(
    file_path
):

    file_path = Path(
        file_path
    )

    try:

        _apply_output_owner(
            file_path
        )

        os.chmod(
            file_path,
            OUTPUT_FILE_MODE,
        )

    except Exception as exc:

        print(
            "Unable to apply output file "
            f"permissions to {file_path}: {exc}"
        )



# ============================================================
# PERSISTENT RIP LOGS
# ============================================================

RIP_LOG_ROOT = (
    SETTINGS_ROOT
    / "logs"
)


def _rip_log_timestamp():
    return (
        datetime.now(
            timezone.utc
        )
        .astimezone()
        .isoformat(
            timespec="seconds"
        )
    )


def _ensure_rip_log_path(job):
    path = job.get(
        "_log_path"
    )

    if path:
        return Path(path)

    RIP_LOG_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    apply_output_directory_permissions(
        RIP_LOG_ROOT
    )

    stamp = (
        datetime.now(
            timezone.utc
        )
        .strftime(
            "%Y%m%d-%H%M%S"
        )
    )

    path = (
        RIP_LOG_ROOT
        / (
            f"{stamp}_"
            f"{job['id']}.txt"
        )
    )

    job["_log_path"] = str(
        path
    )

    return path


def write_rip_log(job):
    try:
        path = (
            _ensure_rip_log_path(
                job
            )
        )

        drive = job.get(
            "_drive",
            {},
        )

        metadata = job.get(
            "_metadata",
            {},
        )

        lines = [
            "ActuallyFreeCD Server Rip Log",
            "=============================",
            "",
            f"Server version: {SERVER_VERSION}",
            f"Rip ID: {job.get('id', '')}",
            f"Updated: {_rip_log_timestamp()}",
            f"Status: {job.get('status', '')}",
            f"Stage: {job.get('stage', '')}",
            f"Message: {job.get('message', '')}",
            f"Error: {job.get('error') or ''}",
            "",
            "Drive",
            "-----",
            f"ID: {job.get('drive_id', '')}",
            f"Vendor: {drive.get('vendor', '')}",
            f"Model: {drive.get('model', '')}",
            f"Revision: {drive.get('revision', '')}",
            f"Device: {drive.get('device', '')}",
            f"Read offset: {job.get('read_offset_samples', 0)} samples",
            "",
            "Disc / Metadata",
            "---------------",
            f"Album artist: {metadata.get('album_artist', '')}",
            f"Album: {metadata.get('album', '')}",
            f"Year: {metadata.get('year', '')}",
            f"Disc number: {metadata.get('disc_number', '')}",
            f"Metadata source: {metadata.get('metadata_source', metadata.get('source', ''))}",
            "",
            "Rip Settings",
            "------------",
            f"Rip mode: {job.get('rip_mode', '')}",
            f"Output format: {job.get('output_format', '')}",
            f"MP3 quality: {job.get('mp3_quality', '')}",
            f"Naming preset: {job.get('naming_preset', '')}",
            f"Destination: {job.get('output_folder') or ''}",
            f"Completed tracks: {job.get('completed_tracks', 0)}/{job.get('total_tracks', 0)}",
            f"Eject after rip: {bool(job.get('eject_after_rip', False))}",
            f"Eject status: {job.get('eject_status') or ''}",
            f"Eject error: {job.get('eject_error') or ''}",
            "",
            "AccurateRip",
            "-----------",
            json.dumps(
                job.get(
                    "accuraterip"
                ),
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            "",
            "Tracks",
            "------",
        ]

        for track in job.get(
            "tracks",
            [],
        ):
            lines.extend([
                (
                    f"Track {track.get('number', '')}: "
                    f"{track.get('artist', '')} - "
                    f"{track.get('title', '')}"
                ),
                f"  Status: {track.get('status', '')}",
                f"  File: {track.get('file') or ''}",
                f"  Error: {track.get('error') or ''}",
                "  Diagnostics:",
                json.dumps(
                    track.get(
                        "diagnostics"
                    ),
                    indent=4,
                    ensure_ascii=False,
                    default=str,
                ),
                "  Rip report:",
                json.dumps(
                    track.get(
                        "rip_report"
                    ),
                    indent=4,
                    ensure_ascii=False,
                    default=str,
                ),
                "",
            ])

        path.write_text(
            "\n".join(
                lines
            )
            + "\n",
            encoding="utf-8",
        )

        apply_output_file_permissions(
            path
        )

        job["log_file"] = str(
            path
        )

    except Exception as exc:
        print(
            "Unable to write rip log "
            f"for {job.get('id')}: {exc}"
        )


# ============================================================
# PATH HELPERS
# ============================================================

def safe_file_name(
    value
):

    value = str(
        value or ""
    ).strip()

    if not value:

        return ""

    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]',
        "_",
        value,
    )

    value = value.rstrip(
        ". "
    )

    return (
        value
        or "Unknown"
    )


# ============================================================
# PROCESS / CANCEL SUPPORT
# ============================================================

def terminate_process(
    job
):

    process = job.get(
        "_process"
    )

    if (
        process is None
        or process.poll()
        is not None
    ):

        return

    try:

        process.terminate()

        try:

            process.wait(
                timeout=3
            )

        except subprocess.TimeoutExpired:

            process.kill()

    except Exception:

        pass



# ============================================================
# ARTWORK HELPERS
# ============================================================

def artwork_path_from_token(
    token
):

    token = str(
        token or ""
    ).strip()

    if not token:

        return None

    safe_token = re.sub(
        r"[^A-Za-z0-9_.-]",
        "",
        token,
    )

    if (
        not safe_token
        or safe_token != token
    ):

        return None

    path = (
        ARTWORK_ROOT
        / safe_token
    )

    if not path.exists():

        return None

    return path


def _release_artwork_cache_path(
    release_id,
    suffix,
):

    safe_id = re.sub(
        r"[^A-Za-z0-9_-]",
        "",
        str(
            release_id
            or ""
        ),
    )

    if not safe_id:

        return None

    return (
        ARTWORK_ROOT
        / (
            "release-"
            f"{safe_id}"
            f"{suffix}"
        )
    )


def find_cached_release_artwork(
    release_id,
):

    for suffix in (
        ".jpg",
        ".png",
    ):

        path = (
            _release_artwork_cache_path(
                release_id,
                suffix,
            )
        )

        if (
            path is not None
            and path.exists()
            and path.stat().st_size > 0
        ):

            return path

    return None


def _download_artwork_url(
    url,
    destination_folder,
    timeout_seconds,
):

    artwork_request = (
        urllib.request.Request(
            url,
            headers={
                "User-Agent":
                    USER_AGENT,

                "Accept":
                    (
                        "image/jpeg,"
                        "image/png,"
                        "image/*;q=0.8"
                    ),
            },
        )
    )

    with urllib.request.urlopen(
        artwork_request,
        timeout=
            timeout_seconds,
    ) as response:

        content_type = (
            response.headers.get(
                "Content-Type",
                "image/jpeg",
            )
            .split(";")[0]
            .strip()
            .lower()
        )

        suffix = (
            ALLOWED_ARTWORK_TYPES.get(
                content_type,
                ".jpg",
            )
        )

        artwork_path = (
            destination_folder
            / (
                "cover"
                f"{suffix}"
            )
        )

        with artwork_path.open(
            "wb"
        ) as file:

            shutil.copyfileobj(
                response,
                file,
            )

    if (
        not artwork_path.exists()
        or artwork_path.stat().st_size
        <= 0
    ):

        return None

    return artwork_path


def download_release_artwork(
    release_id,
    destination_folder,
):

    release_id = str(
        release_id or ""
    ).strip()

    if not release_id:

        return None

    cached = (
        find_cached_release_artwork(
            release_id
        )
    )

    if cached:

        destination = (
            destination_folder
            / cached.name
        )

        shutil.copy2(
            cached,
            destination,
        )

        return destination

    safe_release_id = (
        urllib.parse.quote(
            release_id,
            safe="",
        )
    )

    # Cover Art Archive currently redirects image requests
    # through archive.org and then to an individual storage
    # node. Those final nodes can occasionally return transient
    # 5xx errors or respond very slowly. Try several image sizes,
    # with retries, rather than treating one temporary failure as
    # "no artwork".
    attempts = [
        (
            "front-500",
            12,
        ),
        (
            "front-500",
            12,
        ),
        (
            "front-250",
            12,
        ),
        (
            "front-250",
            12,
        ),
        (
            "front",
            15,
        ),
    ]

    last_error = None

    for endpoint, timeout_seconds in attempts:

        url = (
            "https://coverartarchive.org/"
            f"release/"
            f"{safe_release_id}/"
            f"{endpoint}"
        )

        try:

            downloaded = (
                _download_artwork_url(
                    url,
                    destination_folder,
                    timeout_seconds,
                )
            )

            if downloaded is None:

                continue

            ARTWORK_ROOT.mkdir(
                parents=True,
                exist_ok=True,
            )

            persistent_path = (
                _release_artwork_cache_path(
                    release_id,
                    downloaded.suffix.lower(),
                )
            )

            if persistent_path:

                shutil.copy2(
                    downloaded,
                    persistent_path,
                )

            return downloaded

        except urllib.error.HTTPError as exc:

            last_error = exc

            # A real 404 means this release has no artwork.
            # Do not spend a minute retrying it.
            if exc.code == 404:

                print(
                    "No Cover Art Archive artwork "
                    f"for release {release_id}"
                )

                return None

            # Retry transient upstream failures.
            if exc.code in (
                429,
                500,
                502,
                503,
                504,
            ):

                print(
                    "Temporary artwork HTTP "
                    f"{exc.code} for {endpoint}; "
                    "trying another artwork request."
                )

                continue

            print(
                "Artwork HTTP error "
                f"{exc.code} for {endpoint}: "
                f"{exc}"
            )

        except (
            TimeoutError,
            urllib.error.URLError,
        ) as exc:

            last_error = exc

            print(
                "Artwork request timed out/failed "
                f"for {endpoint}: {exc}"
            )

        except Exception as exc:

            last_error = exc

            print(
                "Unable to download artwork "
                f"from {endpoint}: {exc}"
            )

    if last_error is not None:

        print(
            "Artwork service temporarily "
            "unavailable after retries: "
            f"{last_error}"
        )

    return None


def prepare_rip_artwork(
    metadata,
    work_folder,
):

    artwork_token = (
        metadata.get(
            "artwork_token"
        )
        or ""
    )

    uploaded_path = (
        artwork_path_from_token(
            artwork_token
        )
    )

    if uploaded_path:

        destination = (
            work_folder
            / uploaded_path.name
        )

        shutil.copy2(
            uploaded_path,
            destination,
        )

        return destination

    release_id = (
        metadata.get(
            "release_id"
        )
        or ""
    )

    if (
        metadata.get(
            "artwork_enabled",
            True,
        )
        and release_id
    ):

        return (
            download_release_artwork(
                release_id,
                work_folder,
            )
        )

    return None


# ============================================================
# FLAC ENCODING
# ============================================================

def encode_flac(
    wav_path,
    flac_path,
    track_number,
    title,
    artist,
    metadata,
    physical_track_count,
    artwork_path,
    job,
):

    album_artist = (
        metadata.get(
            "album_artist"
        )
        or "Unknown Artist"
    )

    album = (
        metadata.get(
            "album"
        )
        or "Unknown Album"
    )

    year = (
        metadata.get(
            "year"
        )
        or ""
    )

    genre = (
        metadata.get(
            "genre"
        )
        or ""
    )

    disc_number = int(
        metadata.get(
            "disc_number"
        )
        or 1
    )

    total_discs = int(
        metadata.get(
            "total_discs"
        )
        or 1
    )

    release_id = (
        metadata.get(
            "release_id"
        )
        or ""
    )

    command = [
        "flac",
        "--force",
        "--verify",
        "--best",
        "--output-name",
        str(
            flac_path
        ),

        f"--tag=TITLE={title}",
        f"--tag=ARTIST={artist}",

        (
            "--tag=ALBUMARTIST="
            f"{album_artist}"
        ),

        f"--tag=ALBUM={album}",

        (
            "--tag=TRACKNUMBER="
            f"{track_number}"
        ),

        (
            "--tag=TRACKTOTAL="
            f"{physical_track_count}"
        ),

        (
            "--tag=DISCNUMBER="
            f"{disc_number}"
        ),

        (
            "--tag=DISCTOTAL="
            f"{total_discs}"
        ),
    ]

    if year:

        command.append(
            f"--tag=DATE={year}"
        )

    if genre:

        command.append(
            f"--tag=GENRE={genre}"
        )

    if release_id:

        command.append(
            (
                "--tag=MUSICBRAINZ_"
                "ALBUMID="
                f"{release_id}"
            )
        )

    if (
        artwork_path
        and artwork_path.exists()
    ):

        command.append(
            (
                "--picture="
                f"{artwork_path}"
            )
        )

    command.append(
        str(
            wav_path
        )
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    job["_process"] = (
        process
    )

    stdout, stderr = (
        process.communicate()
    )

    job["_process"] = (
        None
    )

    if process.returncode != 0:

        raise RuntimeError(
            stderr.strip()
            or stdout.strip()
            or (
                "FLAC encoder failed "
                f"with exit code "
                f"{process.returncode}"
            )
        )

    if not flac_path.exists():

        raise RuntimeError(
            (
                "FLAC encoder completed "
                "without creating "
                f"{flac_path.name}"
            )
        )



# ============================================================
# MP3 ENCODING
# ============================================================

def encode_mp3(
    wav_path,
    mp3_path,
    track_number,
    title,
    artist,
    metadata,
    physical_track_count,
    mp3_quality,
    artwork_path,
    job,
):

    album_artist = (
        metadata.get(
            "album_artist"
        )
        or "Unknown Artist"
    )

    album = (
        metadata.get(
            "album"
        )
        or "Unknown Album"
    )

    year = (
        metadata.get(
            "year"
        )
        or ""
    )

    genre = (
        metadata.get(
            "genre"
        )
        or ""
    )

    disc_number = int(
        metadata.get(
            "disc_number"
        )
        or 1
    )

    total_discs = int(
        metadata.get(
            "total_discs"
        )
        or 1
    )

    quality_arguments = {
        "V0 (Highest VBR)": [
            "-V",
            "0",
        ],
        "V2 (High VBR)": [
            "-V",
            "2",
        ],
        "320 kbps CBR": [
            "-b",
            "320",
        ],
    }

    command = [
        "lame",
        *quality_arguments.get(
            mp3_quality,
            [
                "-V",
                "0",
            ],
        ),
        "--id3v2-only",
        "--add-id3v2",
    ]

    def add_option(
        option,
        value,
    ):

        value = str(
            value or ""
        ).strip()

        if value:

            command.extend([
                option,
                value,
            ])

    add_option(
        "--tt",
        title,
    )

    add_option(
        "--ta",
        artist,
    )

    add_option(
        "--tl",
        album,
    )

    add_option(
        "--ty",
        year,
    )

    add_option(
        "--tg",
        genre,
    )

    add_option(
        "--tn",
        (
            f"{track_number}/"
            f"{physical_track_count}"
        ),
    )

    add_option(
        "--tv",
        (
            "TPE2="
            f"{album_artist}"
        ),
    )

    add_option(
        "--tv",
        (
            "TPOS="
            f"{disc_number}/"
            f"{max(total_discs, disc_number)}"
        ),
    )

    if (
        artwork_path
        and artwork_path.exists()
    ):

        add_option(
            "--ti",
            str(
                artwork_path
            ),
        )

    command.extend([
        str(
            wav_path
        ),
        str(
            mp3_path
        ),
    ])

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    job["_process"] = (
        process
    )

    stdout, stderr = (
        process.communicate()
    )

    job["_process"] = (
        None
    )

    if process.returncode != 0:

        try:

            mp3_path.unlink()

        except FileNotFoundError:

            pass

        raise RuntimeError(
            stderr.strip()
            or stdout.strip()
            or (
                "LAME encoder failed "
                f"with exit code "
                f"{process.returncode}"
            )
        )

    if not mp3_path.exists():

        raise RuntimeError(
            (
                "LAME completed without "
                "creating "
                f"{mp3_path.name}"
            )
        )


# ============================================================
# ACCURATERIP DIAGNOSTICS
# ============================================================

def track_database_entries(
    accurate_rip_lookup,
    track_number,
):

    if not accurate_rip_lookup:

        return []

    entries = (
        accurate_rip_lookup.get(
            "entries",
            [],
        )
    )

    results = []

    for entry in entries:

        if (
            int(
                entry.get(
                    "track_number",
                    0,
                )
            )
            != int(
                track_number
            )
        ):

            continue

        results.append({
            "track_number":
                int(
                    entry.get(
                        "track_number",
                        0,
                    )
                ),

            "confidence":
                int(
                    entry.get(
                        "confidence",
                        0,
                    )
                ),

            "crc":
                entry.get(
                    "crc"
                ),

            "crc_text":
                entry.get(
                    "crc_text"
                ),

            "frame450_crc":
                entry.get(
                    "frame450_crc"
                ),

            "frame450_crc_text":
                entry.get(
                    "frame450_crc_text"
                ),
        })

    return results


def build_track_diagnostics(
    track_number,
    report,
    accurate_rip_lookup,
    read_offset_samples,
):

    passes = []

    for pass_info in (
        report.get(
            "passes",
            [],
        )
    ):

        crc = (
            pass_info.get(
                "crc"
            )
            or {}
        )

        verification = (
            pass_info.get(
                "verification"
            )
            or {}
        )

        passes.append({
            "name":
                pass_info.get(
                    "name"
                ),

            "local_arv1":
                crc.get(
                    "v1"
                ),

            "local_arv1_text":
                crc.get(
                    "v1_text"
                ),

            "local_arv2":
                crc.get(
                    "v2"
                ),

            "local_arv2_text":
                crc.get(
                    "v2_text"
                ),

            "matched":
                verification.get(
                    "matched",
                    False,
                ),

            "confidence":
                verification.get(
                    "confidence",
                    0,
                ),

            "matched_crc":
                verification.get(
                    "matched_crc"
                ),

            "matched_crc_text":
                verification.get(
                    "matched_crc_text"
                ),
        })

    return {
        "track_number":
            int(
                track_number
            ),

        "read_offset_samples":
            int(
                read_offset_samples
                or 0
            ),

        "requested_mode":
            report.get(
                "requested_mode"
            ),

        "actual_mode":
            report.get(
                "actual_mode"
            ),

        "used_secure_fallback":
            report.get(
                "used_secure_fallback",
                False,
            ),

        "verified_by_second_read":
            report.get(
                "verified_by_second_read",
                False,
            ),

        "passes":
            passes,

        "database_available":
            accurate_rip_lookup.get(
                "available",
                False,
            ),

        "database_found":
            accurate_rip_lookup.get(
                "found",
                False,
            ),

        "database_error":
            accurate_rip_lookup.get(
                "error"
            ),

        "database_entries":
            track_database_entries(
                accurate_rip_lookup,
                track_number,
            ),
    }



# ============================================================
# MUSIC SUBFOLDER BROWSER
# ============================================================
def resolve_music_subfolder(relative_path=""):
    relative_path=str(relative_path or "").strip().replace("\\","/").strip("/")
    root=MUSIC_ROOT.resolve()
    candidate=(MUSIC_ROOT/relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Folder must remain inside the music library.")
    return candidate,relative_path

@app.route("/api/music-folders",methods=["GET"])
def list_music_folders():
    try:
        folder,clean_path=resolve_music_subfolder(request.args.get("path",""))
        if not folder.exists() or not folder.is_dir(): return jsonify({"error":"Folder does not exist"}),404
        folders=[]
        for child in sorted(folder.iterdir(),key=lambda item:item.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                child_path=f"{clean_path}/{child.name}" if clean_path else child.name
                folders.append({"name":child.name,"path":child_path})
        parent=str(Path(clean_path).parent) if clean_path else ""
        if parent==".": parent=""
        return jsonify({"root":str(MUSIC_ROOT),"path":clean_path,"parent":parent,"folders":folders})
    except ValueError as exc: return jsonify({"error":str(exc)}),400
    except Exception as exc: return jsonify({"error":str(exc)}),500

@app.route("/api/music-folders",methods=["POST"])
def create_music_folder():
    payload=request.get_json(silent=True) or {}
    parent_path=str(payload.get("parent","") or "")
    name=safe_file_name(payload.get("name",""))
    if not name: return jsonify({"error":"Folder name is required"}),400
    try:
        _,clean_parent=resolve_music_subfolder(parent_path)
        destination,clean_path=resolve_music_subfolder(f"{clean_parent}/{name}" if clean_parent else name)
        destination.mkdir(parents=True,exist_ok=True)
        apply_output_directory_permissions(destination)
        return jsonify({"name":name,"path":clean_path})
    except ValueError as exc: return jsonify({"error":str(exc)}),400
    except Exception as exc: return jsonify({"error":str(exc)}),500

# ============================================================
# RIP WORKER
# ============================================================


def build_output_paths(
    output_root,
    metadata,
    track_number,
    title,
    artist,
    naming_preset,
):

    album_artist = safe_file_name(
        metadata.get("album_artist")
        or "Unknown Artist"
    )

    track_artist = safe_file_name(
        artist
        or metadata.get("album_artist")
        or "Unknown Artist"
    )

    album = safe_file_name(
        metadata.get("album")
        or "Unknown Album"
    )

    year = str(
        metadata.get("year")
        or ""
    ).strip()

    disc_number = int(
        metadata.get("disc_number")
        or 1
    )

    safe_title = safe_file_name(
        title
        or f"Track {track_number:02d}"
    )

    album_with_year = (
        f"{album} ({safe_file_name(year)})"
        if year
        else album
    )

    preset = str(
        naming_preset
        or "Artist\\Album (Year)\\## - Title"
    )

    if preset == "Artist\\Album\\## - Title":

        folder = (
            output_root
            / track_artist
            / album
        )

        stem = (
            f"{track_number:02d} - "
            f"{safe_title}"
        )

    elif preset == "Album Artist\\Album (Year)\\Disc #\\## - Title":

        folder = (
            output_root
            / album_artist
            / album_with_year
            / f"Disc {disc_number}"
        )

        stem = (
            f"{track_number:02d} - "
            f"{safe_title}"
        )

    elif preset == "Album Artist\\Album (Year)\\## - Artist - Title":

        folder = (
            output_root
            / album_artist
            / album_with_year
        )

        stem = (
            f"{track_number:02d} - "
            f"{track_artist} - "
            f"{safe_title}"
        )

    else:

        folder = (
            output_root
            / track_artist
            / album_with_year
        )

        stem = (
            f"{track_number:02d} - "
            f"{safe_title}"
        )

    return folder, stem


def rip_worker(
    job_id,
    drive,
    selected_tracks,
    metadata,
    rip_mode,
    read_offset_samples,
    output_format,
    mp3_quality,
    naming_preset,
):

    global last_rip_job_id

    job = jobs[
        job_id
    ]

    work_folder = None

    try:

        device = drive.get(
            "device"
        )

        if not device:

            raise RuntimeError(
                "Drive device path "
                "is unavailable"
            )

        disc = drive.get(
            "disc",
            {},
        )

        work_folder = (
            Path("/tmp")
            / "actuallyfreecd"
            / job_id
        )

        work_folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        artwork_path = (
            prepare_rip_artwork(
                metadata,
                work_folder,
            )
        )

        physical_track_count = (
            disc.get(
                "track_count",
                len(
                    selected_tracks
                ),
            )
        )

        # ----------------------------------------------------
        # ACCURATERIP LOOKUP
        # ----------------------------------------------------

        job["stage"] = (
            "accuraterip_lookup"
        )

        job["message"] = (
            "Checking AccurateRip..."
        )

        accurate_rip_lookup = (
            accuraterip
            .query_database(
                disc
            )
        )

        job["accuraterip"] = {
            "available":
                accurate_rip_lookup.get(
                    "available"
                ),

            "found":
                accurate_rip_lookup.get(
                    "found"
                ),

            "error":
                accurate_rip_lookup.get(
                    "error"
                ),

            "disc_id":
                accurate_rip_lookup.get(
                    "disc_id"
                ),
        }

        job["status"] = (
            "running"
        )

        write_rip_log(
            job
        )

        total_tracks = len(
            selected_tracks
        )

        for index, track in enumerate(
            selected_tracks
        ):

            if job[
                "_cancel"
            ].is_set():

                raise (
                    ripper.RipCancelled(
                        "Rip cancelled"
                    )
                )

            track_number = int(
                track[
                    "number"
                ]
            )

            title = (
                track.get(
                    "title"
                )
                or (
                    f"Track "
                    f"{track_number:02d}"
                )
            )

            artist = (
                track.get(
                    "artist"
                )
                or metadata.get(
                    "album_artist"
                )
                or "Unknown Artist"
            )

            wav_path = (
                work_folder
                / (
                    f"track"
                    f"{track_number:02d}.wav"
                )
            )

            output_folder, output_stem = (
                build_output_paths(
                    output_root=
                        resolve_music_subfolder(
                            metadata.get(
                                "output_subfolder",
                                ""
                            )
                        )[0],

                    metadata=
                        metadata,

                    track_number=
                        track_number,

                    title=
                        title,

                    artist=
                        artist,

                    naming_preset=
                        naming_preset,
                )
            )

            output_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            apply_output_directory_permissions(
                output_folder
            )

            job[
                "output_folder"
            ] = str(
                output_folder
            )

            flac_path = (
                output_folder
                / f"{output_stem}.flac"
            )

            mp3_path = (
                output_folder
                / f"{output_stem}.mp3"
            )

            track_status = (
                job[
                    "tracks"
                ][
                    index
                ]
            )

            job[
                "current_track"
            ] = track_number

            job["stage"] = (
                "reading"
            )

            track_status[
                "status"
            ] = "Starting"

            # ------------------------------------------------
            # RIPPER CALLBACKS
            # ------------------------------------------------

            def set_process(
                process
            ):

                job[
                    "_process"
                ] = process


            def set_status(
                text
            ):

                job[
                    "message"
                ] = text

                track_status[
                    "status"
                ] = text


            def set_track_progress(
                track_percent
            ):

                track_percent = max(
                    0.0,
                    min(
                        100.0,
                        float(
                            track_percent
                        ),
                    ),
                )

                completed_fraction = (
                    index
                    + (
                        track_percent
                        / 100.0
                    )
                    * 0.90
                )

                job["progress"] = (
                    completed_fraction
                    / total_tracks
                    * 100.0
                )

                track_status[
                    "status"
                ] = (
                    f"Reading "
                    f"{track_percent:.0f}%"
                )

            # ------------------------------------------------
            # RIP TO WAV
            # ------------------------------------------------

            report = (
                ripper
                .rip_track_to_wav(
                    device=
                        device,

                    disc=
                        disc,

                    track_number=
                        track_number,

                    output_path=
                        wav_path,

                    rip_mode=
                        rip_mode,

                    read_offset_samples=
                        read_offset_samples,

                    accurate_rip_lookup=
                        accurate_rip_lookup,

                    cancel_event=
                        job["_cancel"],

                    progress_callback=
                        set_track_progress,

                    status_callback=
                        set_status,

                    process_callback=
                        set_process,
                )
            )

            job[
                "_process"
            ] = None

            track_status[
                "diagnostics"
            ] = (
                build_track_diagnostics(
                    track_number,
                    report,
                    accurate_rip_lookup,
                    read_offset_samples,
                )
            )

            # ------------------------------------------------
            # ENCODE OUTPUT
            # ------------------------------------------------

            job["stage"] = (
                "encoding"
            )

            track_status[
                "status"
            ] = "Encoding"

            job["progress"] = (
                (
                    index
                    + 0.93
                )
                / total_tracks
                * 100.0
            )

            output_files = []

            if output_format in (
                "FLAC",
                "FLAC + MP3",
            ):

                job["message"] = (
                    f"Encoding track "
                    f"{track_number:02d} "
                    f"to FLAC..."
                )

                encode_flac(
                    wav_path=
                        wav_path,

                    flac_path=
                        flac_path,

                    track_number=
                        track_number,

                    title=
                        title,

                    artist=
                        artist,

                    metadata=
                        metadata,

                    physical_track_count=
                        physical_track_count,

                    artwork_path=
                        artwork_path,

                    job=
                        job,
                )

                apply_output_file_permissions(
                    flac_path
                )

                output_files.append(
                    str(
                        flac_path
                    )
                )

            if output_format in (
                "MP3",
                "FLAC + MP3",
            ):

                job["message"] = (
                    f"Encoding track "
                    f"{track_number:02d} "
                    f"to MP3..."
                )

                encode_mp3(
                    wav_path=
                        wav_path,

                    mp3_path=
                        mp3_path,

                    track_number=
                        track_number,

                    title=
                        title,

                    artist=
                        artist,

                    metadata=
                        metadata,

                    physical_track_count=
                        physical_track_count,

                    mp3_quality=
                        mp3_quality,

                    artwork_path=
                        artwork_path,

                    job=
                        job,
                )

                apply_output_file_permissions(
                    mp3_path
                )

                output_files.append(
                    str(
                        mp3_path
                    )
                )

            try:

                wav_path.unlink()

            except FileNotFoundError:

                pass

            result_text = (
                ripper
                .result_status_text(
                    report,
                    accurate_rip_lookup,
                )
            )

            track_status[
                "status"
            ] = result_text

            track_status[
                "file"
            ] = (
                output_files[0]
                if len(
                    output_files
                ) == 1
                else None
            )

            track_status[
                "files"
            ] = (
                output_files
            )

            track_status[
                "rip_report"
            ] = report

            job[
                "completed_tracks"
            ] = (
                index + 1
            )

            job["progress"] = (
                (
                    index + 1
                )
                / total_tracks
                * 100.0
            )

            write_rip_log(
                job
            )

        job["status"] = (
            "complete"
        )

        job["stage"] = (
            "complete"
        )

        job[
            "current_track"
        ] = None

        job["progress"] = (
            100.0
        )

        job["message"] = (
            f"Rip complete — "
            f"{total_tracks} track"
            f"{'' if total_tracks == 1 else 's'}"
        )

        if job.get(
            "eject_after_rip",
            False,
        ):

            try:
                eject_drive_device(
                    drive
                )

                job[
                    "eject_status"
                ] = "ejected"

            except Exception as exc:
                job[
                    "eject_status"
                ] = "failed"

                job[
                    "eject_error"
                ] = str(
                    exc
                )

                print(
                    "Rip completed, but "
                    "automatic eject failed: "
                    f"{exc}"
                )

    except ripper.RipCancelled:

        job["status"] = (
            "cancelled"
        )

        job["stage"] = (
            "cancelled"
        )

        job[
            "current_track"
        ] = None

        job["message"] = (
            "Rip cancelled — "
            "completed tracks were kept."
        )

    except Exception as exc:

        if job.get("_cancel") is not None and job["_cancel"].is_set():
            job["status"] = "cancelled"
            job["stage"] = "cancelled"
            job["current_track"] = None
            job["error"] = None
            job["message"] = "Rip cancelled — completed tracks were kept."
            for track in job["tracks"]:
                if track.get("status") not in ("Complete", "Completed"):
                    track["status"] = "Cancelled"
                    track["error"] = None
            return

        job["status"] = (
            "failed"
        )

        job["stage"] = (
            "failed"
        )

        job["error"] = (
            str(
                exc
            )
        )

        job["message"] = (
            "Rip failed."
        )

        if (
            job[
                "current_track"
            ]
            is not None
        ):

            for track in (
                job[
                    "tracks"
                ]
            ):

                if (
                    track["number"]
                    == job[
                        "current_track"
                    ]
                ):

                    track[
                        "status"
                    ] = "Failed"

                    track[
                        "error"
                    ] = str(
                        exc
                    )

                    break

    finally:

        last_rip_job_id = (
            job_id
        )

        write_rip_log(
            job
        )

        terminate_process(
            job
        )

        job[
            "_process"
        ] = None

        if work_folder:

            try:

                for item in (
                    work_folder
                    .iterdir()
                ):

                    try:

                        item.unlink()

                    except Exception:

                        pass

                work_folder.rmdir()

            except Exception:

                pass


# ============================================================
# WEB PAGE
# ============================================================

@app.route("/favicon.ico")
def favicon():

    return app.send_static_file(
        "ActuallyFreeCD.png"
    )


@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# STATUS
# ============================================================

@app.route(
    "/api/status"
)
def status():

    return jsonify({
        "name":
            "ActuallyFreeCD Server",

        "version":
            SERVER_VERSION,

        "status":
            "running",

        "music_root":
            str(
                MUSIC_ROOT
            ),

        "music_destination":
            get_music_root_status(),

        "settings_file":
            str(
                DRIVE_SETTINGS_FILE
            ),

        "output_permissions": {
            "uid":
                OUTPUT_UID,

            "gid":
                OUTPUT_GID,

            "directory_mode":
                format(
                    EFFECTIVE_DIR_MODE,
                    "04o",
                ),

            "file_mode":
                format(
                    OUTPUT_FILE_MODE,
                    "04o",
                ),
        },
    })


# ============================================================
# DRIVE SETTINGS API
# ============================================================

@app.route(
    "/api/drives/"
    "<drive_id>/settings",
    methods=["GET"],
)
def drive_settings_get(
    drive_id
):

    drive = find_drive(
        drive_id
    )

    if drive is None:

        return jsonify({
            "error":
                "Drive not found",

            "drive_id":
                drive_id,
        }), 404

    initialise_drive_settings(
        drive_id,
        drive,
    )

    settings = (
        get_drive_settings(
            drive_id
        )
    )

    return jsonify({
        "server":
            "ActuallyFreeCD Server",

        "version":
            SERVER_VERSION,

        "drive": {
            "id":
                drive.get(
                    "id"
                ),

            "vendor":
                drive.get(
                    "vendor"
                ),

            "model":
                drive.get(
                    "model"
                ),

            "serial":
                drive.get(
                    "serial"
                ),
        },

        "settings":
            settings,
    })


@app.route(
    "/api/drives/"
    "<drive_id>/settings",
    methods=["POST"],
)
def drive_settings_save(
    drive_id
):

    drive = find_drive(
        drive_id
    )

    if drive is None:

        return jsonify({
            "error":
                "Drive not found",

            "drive_id":
                drive_id,
        }), 404

    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    if (
        "read_offset_samples"
        not in payload
    ):

        return jsonify({
            "error":
                "read_offset_samples "
                "is required"
        }), 400

    try:

        settings = (
            set_drive_settings(
                drive_id,
                payload[
                    "read_offset_samples"
                ],
            )
        )

    except (
        TypeError,
        ValueError,
    ) as exc:

        return jsonify({
            "error":
                str(
                    exc
                )
        }), 400

    except Exception as exc:

        return jsonify({
            "error":
                (
                    "Unable to save "
                    "drive settings: "
                    f"{exc}"
                )
        }), 500

    return jsonify({
        "server":
            "ActuallyFreeCD Server",

        "version":
            SERVER_VERSION,

        "drive": {
            "id":
                drive.get(
                    "id"
                ),

            "vendor":
                drive.get(
                    "vendor"
                ),

            "model":
                drive.get(
                    "model"
                ),
        },

        "settings":
            settings,
    })


# ============================================================
# LAST RIP DIAGNOSTICS
# ============================================================

@app.route(
    "/api/diagnostics/last-rip"
)
def last_rip_diagnostics():

    if (
        last_rip_job_id
        is None
    ):

        return jsonify({
            "server":
                "ActuallyFreeCD Server",

            "version":
                SERVER_VERSION,

            "message":
                (
                    "No rip has been performed "
                    "since the server started."
                ),
        })

    job = jobs.get(
        last_rip_job_id
    )

    if job is None:

        return jsonify({
            "error":
                (
                    "Last rip job is "
                    "no longer available"
                )
        }), 404

    diagnostic_tracks = []

    for track in (
        job.get(
            "tracks",
            []
        )
    ):

        diagnostic_tracks.append({
            "number":
                track.get(
                    "number"
                ),

            "title":
                track.get(
                    "title"
                ),

            "status":
                track.get(
                    "status"
                ),

            "diagnostics":
                track.get(
                    "diagnostics"
                ),
        })

    return jsonify({
        "server":
            "ActuallyFreeCD Server",

        "version":
            SERVER_VERSION,

        "job_id":
            job.get(
                "id"
            ),

        "status":
            job.get(
                "status"
            ),

        "rip_mode":
            job.get(
                "rip_mode"
            ),

        "read_offset_samples":
            job.get(
                "read_offset_samples"
            ),

        "accuraterip":
            job.get(
                "accuraterip"
            ),

        "tracks":
            diagnostic_tracks,
    })



# ============================================================
# MANUAL ARTWORK
# ============================================================

@app.route(
    "/api/artwork/upload",
    methods=["POST"],
)
def upload_artwork():

    artwork = request.files.get(
        "artwork"
    )

    if (
        artwork is None
        or not artwork.filename
    ):

        return jsonify({
            "error":
                "No artwork file supplied"
        }), 400

    content_type = (
        artwork.mimetype
        or ""
    ).lower()

    suffix = (
        ALLOWED_ARTWORK_TYPES.get(
            content_type
        )
    )

    if suffix is None:

        return jsonify({
            "error":
                (
                    "Artwork must be "
                    "JPEG or PNG"
                )
        }), 400

    data = artwork.read(
        MAX_ARTWORK_BYTES + 1
    )

    if len(data) > MAX_ARTWORK_BYTES:

        return jsonify({
            "error":
                (
                    "Artwork is larger "
                    "than 10 MB"
                )
        }), 413

    ARTWORK_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    token = (
        f"{uuid.uuid4().hex}"
        f"{suffix}"
    )

    path = (
        ARTWORK_ROOT
        / token
    )

    with path.open(
        "wb"
    ) as file:

        file.write(
            data
        )

    return jsonify({
        "token":
            token,

        "url":
            (
                "/api/artwork/"
                f"{token}"
            ),
    })


@app.route(
    "/api/artwork/<token>"
)
def uploaded_artwork(
    token
):

    path = artwork_path_from_token(
        token
    )

    if path is None:

        return jsonify({
            "error":
                "Artwork not found"
        }), 404

    content_type = (
        "image/png"
        if path.suffix.lower()
        == ".png"
        else "image/jpeg"
    )

    return Response(
        path.read_bytes(),
        status=200,
        content_type=
            content_type,
        headers={
            "Cache-Control":
                (
                    "private, "
                    "max-age=86400"
                )
        },
    )



@app.route(
    "/api/releases/"
    "<release_id>/artwork-cache",
    methods=["POST"],
)
def release_artwork_cache(
    release_id
):

    ARTWORK_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_folder = (
        Path("/tmp")
        / "actuallyfreecd"
        / "artwork-cache"
        / uuid.uuid4().hex
    )

    temp_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:

        downloaded = (
            download_release_artwork(
                release_id,
                temp_folder,
            )
        )

        if downloaded is None:

            return jsonify({
                "error":
                    (
                        "Album artwork is currently "
                        "unavailable. Ripping can "
                        "continue without artwork."
                    )
            }), 503

        # Use the persistent release cache itself as the token
        # where possible, so the exact image shown in the UI is
        # the image later embedded into FLAC/MP3.
        persistent = (
            find_cached_release_artwork(
                release_id
            )
        )

        if persistent:

            token = (
                persistent.name
            )

        else:

            token = (
                f"{uuid.uuid4().hex}"
                f"{downloaded.suffix.lower()}"
            )

            destination = (
                ARTWORK_ROOT
                / token
            )

            shutil.copy2(
                downloaded,
                destination,
            )

        return jsonify({
            "token":
                token,

            "url":
                (
                    "/api/artwork/"
                    f"{token}"
                ),
        })

    finally:

        try:

            shutil.rmtree(
                temp_folder,
                ignore_errors=True,
            )

        except Exception:

            pass


# ============================================================
# COVER ART
# ============================================================

@app.route(
    "/api/releases/"
    "<release_id>/artwork"
)
def release_artwork(
    release_id
):

    try:

        safe_release_id = (
            urllib.parse.quote(
                release_id,
                safe="",
            )
        )

        url = (
            "https://coverartarchive.org/"
            f"release/"
            f"{safe_release_id}/"
            "front-250"
        )

        artwork_request = (
            urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        USER_AGENT,
                },
            )
        )

        with urllib.request.urlopen(
            artwork_request,
            timeout=30,
        ) as response:

            data = (
                response.read()
            )

            content_type = (
                response.headers.get(
                    "Content-Type",
                    "image/jpeg",
                )
            )

        return Response(
            data,
            status=200,
            content_type=
                content_type,
            headers={
                "Cache-Control":
                    (
                        "public, "
                        "max-age=86400"
                    )
            },
        )

    except urllib.error.HTTPError as exc:

        if exc.code == 404:

            return jsonify({
                "error":
                    (
                        "No cover "
                        "artwork found"
                    )
            }), 404

        return jsonify({
            "error":
                (
                    "Cover Art Archive "
                    "returned HTTP "
                    f"{exc.code}"
                )
        }), 502

    except Exception as exc:

        return jsonify({
            "error":
                str(
                    exc
                )
        }), 502


# ============================================================
# DRIVES
# ============================================================

@app.route(
    "/api/drives"
)
def drives():

    try:

        discovered = (
            find_cd_drives()
        )

        return jsonify({
            "server":
                "ActuallyFreeCD Server",

            "version":
                SERVER_VERSION,

            "drive_count":
                len(
                    discovered
                ),

            "drives":
                discovered,
        })

    except Exception as exc:

        return jsonify({
            "server":
                "ActuallyFreeCD Server",

            "version":
                SERVER_VERSION,

            "error":
                str(
                    exc
                ),

            "drives":
                [],
        }), 500


# ============================================================
# MUSICBRAINZ
# ============================================================

@app.route(
    "/api/drives/"
    "<drive_id>/metadata"
)
def drive_metadata(
    drive_id
):

    try:

        drive = (
            find_drive(
                drive_id
            )
        )

        if drive is None:

            return jsonify({
                "error":
                    "Drive not found",

                "drive_id":
                    drive_id,
            }), 404

        disc = drive.get(
            "disc",
            {},
        )

        if not disc.get(
            "present"
        ):

            return jsonify({
                "error":
                    (
                        "No readable disc "
                        "is present"
                    ),

                "drive_id":
                    drive_id,
            }), 404

        if not disc.get(
            "audio"
        ):

            return jsonify({
                "error":
                    (
                        "Disc is not "
                        "an audio CD"
                    ),

                "drive_id":
                    drive_id,
            }), 400

        metadata_source = (
            request.args.get(
                "source",
                "musicbrainz",
            )
            .strip()
            .lower()
        )

        if metadata_source in (
            "cdtext",
            "cd-text",
            "cd_text",
        ):

            metadata = (
                lookup_cdtext(
                    drive.get(
                        "device"
                    ),
                    disc.get(
                        "tracks",
                        [],
                    ),
                )
            )

        elif metadata_source in (
            "musicbrainz",
            "mb",
        ):

            metadata = (
                lookup_disc(
                    disc.get(
                        "tracks",
                        [],
                    )
                )
            )

            metadata[
                "source"
            ] = "musicbrainz"

        else:

            return jsonify({
                "error":
                    (
                        "Unknown metadata source: "
                        f"{metadata_source}"
                    ),

                "valid_sources": [
                    "musicbrainz",
                    "cdtext",
                ],
            }), 400

        return jsonify({
            "server":
                "ActuallyFreeCD Server",

            "version":
                SERVER_VERSION,

            "drive": {
                "id":
                    drive.get(
                        "id"
                    ),

                "vendor":
                    drive.get(
                        "vendor"
                    ),

                "model":
                    drive.get(
                        "model"
                    ),

                "serial":
                    drive.get(
                        "serial"
                    ),
            },

            "metadata":
                metadata,
        })

    except Exception as exc:

        return jsonify({
            "error":
                str(
                    exc
                ),

            "drive_id":
                drive_id,
        }), 500


# ============================================================
# START RIP
# ============================================================

@app.route(
    "/api/drives/"
    "<drive_id>/rip",
    methods=["POST"],
)
def start_rip(
    drive_id
):

    try:

        drive = (
            find_drive(
                drive_id
            )
        )

        if drive is None:

            return jsonify({
                "error":
                    "Drive not found"
            }), 404

        disc = drive.get(
            "disc",
            {},
        )

        if not (
            disc.get(
                "present"
            )
            and disc.get(
                "audio"
            )
        ):

            return jsonify({
                "error":
                    (
                        "No readable audio "
                        "CD is present"
                    )
            }), 400

        destination_status = (
            get_music_root_status()
        )

        if not destination_status.get(
            "writable"
        ):

            return jsonify({
                "error":
                    (
                        destination_status.get(
                            "error"
                        )
                        or (
                            "Music destination "
                            "is not writable."
                        )
                    ),

                "music_destination":
                    destination_status,
            }), 500

        payload = (
            request.get_json(
                silent=True
            )
            or {}
        )

        selected_tracks = (
            payload.get(
                "tracks",
                [],
            )
        )

        metadata = (
            payload.get(
                "metadata",
                {},
            )
        )

        rip_mode = (
            payload.get(
                "rip_mode",
                ripper
                .RIP_MODE_AUTOMATIC,
            )
        )

        output_format = (
            payload.get(
                "output_format",
                "FLAC",
            )
        )

        mp3_quality = (
            payload.get(
                "mp3_quality",
                "V0 (Highest VBR)",
            )
        )

        naming_preset = (
            payload.get(
                "naming_preset",
                "Artist\\Album (Year)\\## - Title",
            )
        )

        eject_after_rip = bool(
            payload.get(
                "eject_after_rip",
                False,
            )
        )

        # IMPORTANT:
        # The server now obtains the offset from the
        # persistent per-drive settings. The browser no
        # longer decides which offset should be used.
        drive_settings = (
            get_drive_settings(
                drive_id
            )
        )

        read_offset_samples = int(
            drive_settings[
                "read_offset_samples"
            ]
        )

        if not selected_tracks:

            return jsonify({
                "error":
                    (
                        "Select at least "
                        "one track"
                    )
            }), 400

        if (
            rip_mode
            not in
            ripper
            .VALID_RIP_MODES
        ):

            return jsonify({
                "error":
                    (
                        "Invalid rip mode: "
                        f"{rip_mode}"
                    )
            }), 400

        valid_output_formats = {
            "FLAC",
            "MP3",
            "FLAC + MP3",
        }

        if (
            output_format
            not in valid_output_formats
        ):

            return jsonify({
                "error":
                    (
                        "Invalid output format: "
                        f"{output_format}"
                    )
            }), 400

        valid_mp3_qualities = {
            "V0 (Highest VBR)",
            "V2 (High VBR)",
            "320 kbps CBR",
        }

        if (
            mp3_quality
            not in valid_mp3_qualities
        ):

            return jsonify({
                "error":
                    (
                        "Invalid MP3 quality: "
                        f"{mp3_quality}"
                    )
            }), 400

        valid_track_numbers = {
            int(
                track[
                    "number"
                ]
            )
            for track in (
                disc.get(
                    "tracks",
                    [],
                )
            )
        }

        requested_numbers = []

        for track in (
            selected_tracks
        ):

            number = int(
                track[
                    "number"
                ]
            )

            if (
                number
                not in
                valid_track_numbers
            ):

                return jsonify({
                    "error":
                        (
                            f"Track {number} "
                            "does not exist "
                            "on this disc"
                        )
                }), 400

            requested_numbers.append(
                number
            )

        if (
            len(
                requested_numbers
            )
            != len(
                set(
                    requested_numbers
                )
            )
        ):

            return jsonify({
                "error":
                    (
                        "Duplicate track "
                        "numbers were supplied"
                    )
            }), 400

        with jobs_lock:

            for existing in (
                jobs.values()
            ):

                if (
                    existing[
                        "drive_id"
                    ]
                    == drive_id
                    and existing[
                        "status"
                    ]
                    in (
                        "queued",
                        "running",
                    )
                ):

                    return jsonify({
                        "error":
                            (
                                "This drive "
                                "is already ripping"
                            ),

                        "job":
                            public_job(
                                existing
                            ),
                    }), 409

            job_id = str(
                uuid.uuid4()
            )

            job_tracks = []

            for track in (
                selected_tracks
            ):

                job_tracks.append({
                    "number":
                        int(
                            track[
                                "number"
                            ]
                        ),

                    "title":
                        track.get(
                            "title",
                            "",
                        ),

                    "artist":
                        track.get(
                            "artist",
                            "",
                        ),

                    "status":
                        "Queued",

                    "file":
                        None,

                    "error":
                        None,

                    "diagnostics":
                        None,
                })

            job = {
                "id":
                    job_id,

                "drive_id":
                    drive_id,

                "status":
                    "queued",

                "stage":
                    "queued",

                "progress":
                    0.0,

                "current_track":
                    None,

                "completed_tracks":
                    0,

                "total_tracks":
                    len(
                        selected_tracks
                    ),

                "output_folder":
                    None,

                "message":
                    "Rip queued.",

                "error":
                    None,

                "tracks":
                    job_tracks,

                "rip_mode":
                    rip_mode,

                "output_format":
                    output_format,

                "mp3_quality":
                    mp3_quality,

                "naming_preset":
                    naming_preset,

                "read_offset_samples":
                    read_offset_samples,

                "accuraterip":
                    None,

                "log_file":
                    None,

                "eject_after_rip":
                    eject_after_rip,

                "eject_status":
                    None,

                "eject_error":
                    None,

                "_drive":
                    {
                        "id": drive.get("id"),
                        "vendor": drive.get("vendor"),
                        "model": drive.get("model"),
                        "revision": drive.get("revision"),
                        "device": drive.get("device"),
                    },

                "_metadata":
                    dict(metadata),

                "_cancel":
                    threading.Event(),

                "_process":
                    None,
            }

            jobs[
                job_id
            ] = job

        worker = threading.Thread(
            target=rip_worker,
            args=(
                job_id,
                drive,
                selected_tracks,
                metadata,
                rip_mode,
                read_offset_samples,
                output_format,
                mp3_quality,
                naming_preset,
            ),
            daemon=True,
        )

        worker.start()

        return jsonify({
            "job":
                public_job(
                    job
                )
        }), 202

    except Exception as exc:

        return jsonify({
            "error":
                str(
                    exc
                )
        }), 500



# ============================================================
# EJECT DISC
# ============================================================

def eject_drive_device(
    drive
):
    device = (
        drive.get(
            "device"
        )
    )

    if not device:
        raise RuntimeError(
            "Drive device path is unavailable."
        )

    import fcntl

    # Linux optical-drive ioctls from <linux/cdrom.h>.
    # TOC/ripping access can leave media removal locked.
    CDROMEJECT = 0x5309
    CDROM_LOCKDOOR = 0x5329

    fd = os.open(
        str(
            device
        ),
        os.O_RDONLY
        | os.O_NONBLOCK,
    )

    try:
        fcntl.ioctl(
            fd,
            CDROM_LOCKDOOR,
            0,
        )

        fcntl.ioctl(
            fd,
            CDROMEJECT,
            0,
        )

    finally:
        os.close(
            fd
        )



@app.route("/api/drives/<drive_id>/eject", methods=["POST"])
def eject_disc(drive_id):
    drive = find_drive(drive_id)
    if drive is None:
        return jsonify({"error": "Drive not found"}), 404

    for existing in jobs.values():
        if (
            existing.get("drive_id") == drive_id
            and existing.get("status") in ("queued", "running")
        ):
            return jsonify({
                "error": "Cannot eject while this drive is ripping."
            }), 409

    try:
        eject_drive_device(
            drive
        )

    except PermissionError:
        return jsonify({
            "error": "Permission denied while opening the optical drive."
        }), 403
    except OSError as exc:
        return jsonify({
            "error": "Unable to eject disc: " + str(exc)
        }), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"status": "ejected", "drive_id": drive_id})


# ============================================================
# ACTIVE RIP SESSION
# ============================================================

@app.route(
    "/api/drives/"
    "<drive_id>/active-rip"
)
def active_rip_session(
    drive_id
):

    active = None

    with jobs_lock:

        for job in (
            jobs.values()
        ):

            if (
                job.get(
                    "drive_id"
                )
                == drive_id
                and job.get(
                    "status"
                )
                in (
                    "queued",
                    "running",
                )
            ):
                active = job

    return jsonify({
        "active":
            active is not None,

        "job":
            (
                public_job(
                    active
                )
                if active is not None
                else None
            ),
    })


# ============================================================
# JOB STATUS
# ============================================================

@app.route(
    "/api/jobs/<job_id>"
)
def rip_job_status(
    job_id
):

    job = jobs.get(
        job_id
    )

    if job is None:

        return jsonify({
            "error":
                "Rip job not found"
        }), 404

    return jsonify({
        "job":
            public_job(
                job
            )
    })


# ============================================================
# CANCEL
# ============================================================

@app.route(
    "/api/jobs/"
    "<job_id>/cancel",
    methods=["POST"],
)
def cancel_rip(
    job_id
):

    job = jobs.get(
        job_id
    )

    if job is None:

        return jsonify({
            "error":
                "Rip job not found"
        }), 404

    if (
        job[
            "status"
        ]
        not in (
            "queued",
            "running",
        )
    ):

        return jsonify({
            "error":
                (
                    "Rip job is "
                    "not running"
                ),

            "job":
                public_job(
                    job
                ),
        }), 409

    job[
        "_cancel"
    ].set()

    job["message"] = (
        "Stopping rip safely..."
    )

    terminate_process(
        job
    )

    return jsonify({
        "job":
            public_job(
                job
            )
    })


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    print(
        f"ActuallyFreeCD Server "
        f"v{SERVER_VERSION}"
    )

    print(
        "Listening on port 8080"
    )

    print(
        f"Music destination: "
        f"{MUSIC_ROOT}"
    )

    print(
        "Drive settings: "
        f"{DRIVE_SETTINGS_FILE}"
    )

    app.run(
        host="0.0.0.0",
        port=8080,
        threaded=True,
    )