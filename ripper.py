import shutil
import subprocess
import threading
import time

from pathlib import Path

import accuraterip


RIP_MODE_AUTOMATIC = "Automatic"
RIP_MODE_FAST = "Fast"
RIP_MODE_SECURE = "Secure"

VALID_RIP_MODES = {
    RIP_MODE_AUTOMATIC,
    RIP_MODE_FAST,
    RIP_MODE_SECURE,
}

CD_AUDIO_BYTES_PER_SECTOR = 2352

CDPARANOIA_STALL_TIMEOUT_SECONDS = 90
CDPARANOIA_POLL_SECONDS = 0.20


# ============================================================
# EXCEPTIONS
# ============================================================

class RipCancelled(Exception):
    pass


# ============================================================
# GENERAL HELPERS
# ============================================================

def _normalise_mode(mode):
    value = str(
        mode or RIP_MODE_AUTOMATIC
    ).strip()

    for valid in VALID_RIP_MODES:
        if value.lower() == valid.lower():
            return valid

    raise ValueError(
        f"Unknown rip mode: {value}"
    )


def _find_track(
    disc,
    track_number,
):
    track_number = int(
        track_number
    )

    for track in disc.get(
        "tracks",
        [],
    ):
        if int(
            track.get(
                "number",
                0,
            )
        ) == track_number:
            return track

    raise ValueError(
        f"Track {track_number} "
        "does not exist on this disc."
    )


def _track_index(
    disc,
    track_number,
):
    track_number = int(
        track_number
    )

    for index, track in enumerate(
        disc.get(
            "tracks",
            [],
        )
    ):
        if int(
            track.get(
                "number",
                0,
            )
        ) == track_number:
            return index

    raise ValueError(
        f"Track {track_number} "
        "does not exist on this disc."
    )


def _is_first_track(
    disc,
    track_number,
):
    tracks = disc.get(
        "tracks",
        [],
    )

    if not tracks:
        return False

    return int(
        tracks[0]["number"]
    ) == int(track_number)


def _is_last_track(
    disc,
    track_number,
):
    tracks = disc.get(
        "tracks",
        [],
    )

    if not tracks:
        return False

    return int(
        tracks[-1]["number"]
    ) == int(track_number)


def _expected_track_bytes(
    track
):
    sectors = int(
        track.get(
            "sectors",
            0,
        )
        or 0
    )

    return (
        sectors
        * CD_AUDIO_BYTES_PER_SECTOR
    )


def _safe_unlink(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ============================================================
# PROCESS CONTROL
# ============================================================

def _terminate_process(
    process,
):
    if (
        process is None
        or process.poll() is not None
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


def _run_cdparanoia(
    command,
    output_path,
    expected_bytes,
    cancel_event=None,
    progress_callback=None,
    process_callback=None,
):
    """
    Run cdparanoia and report approximate extraction progress
    by watching the WAV file grow.

    progress_callback(percent) is optional.

    process_callback(process_or_none) allows server.py to keep
    track of the currently running subprocess for STOP support.
    """

    output_path = Path(
        output_path
    )

    _safe_unlink(
        output_path
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if process_callback is not None:
        process_callback(
            process
        )

    last_size = -1
    last_growth_time = time.monotonic()

    try:
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                _terminate_process(process)
                raise RipCancelled("Rip cancelled")

            try:
                size = output_path.stat().st_size
            except FileNotFoundError:
                size = 0

            if size != last_size:
                last_size = size
                last_growth_time = time.monotonic()
            elif time.monotonic() - last_growth_time >= CDPARANOIA_STALL_TIMEOUT_SECONDS:
                _terminate_process(process)
                raise RuntimeError(
                    "CD read stalled — no audio data was written "
                    f"for {CDPARANOIA_STALL_TIMEOUT_SECONDS} seconds."
                )

            if progress_callback is not None and expected_bytes > 0:
                percent = max(0.0, min(99.5, size / expected_bytes * 100.0))
                progress_callback(percent)

            time.sleep(CDPARANOIA_POLL_SECONDS)

        stdout, stderr = process.communicate()

        if cancel_event is not None and cancel_event.is_set():
            raise RipCancelled("Rip cancelled")

        if process.returncode != 0:
            message = (
                stderr.strip()
                or stdout.strip()
                or (
                    "cdparanoia failed "
                    f"with exit code "
                    f"{process.returncode}"
                )
            )

            raise RuntimeError(
                message
            )

        if not output_path.exists():
            raise RuntimeError(
                "cdparanoia completed "
                "without creating the "
                "expected WAV file."
            )

        if progress_callback is not None:
            progress_callback(
                100.0
            )

        return {
            "stdout":
                stdout,

            "stderr":
                stderr,
        }

    finally:

        if process_callback is not None:
            process_callback(
                None
            )


# ============================================================
# CDPARANOIA COMMANDS
# ============================================================

def _build_cdparanoia_command(
    device,
    track_number,
    output_path,
    fast,
    read_offset_samples=0,
):
    command = [
        "cdparanoia",
        "-d",
        str(device),
    ]

    read_offset_samples = int(
        read_offset_samples
        or 0
    )

    if read_offset_samples != 0:
        command.extend([
            "-O",
            str(
                read_offset_samples
            ),
        ])

    if fast:
        # Disable cdparanoia data verification/correction.
        command.append(
            "-Z"
        )

    command.extend([
        str(
            int(track_number)
        ),
        str(output_path),
    ])

    return command


# ============================================================
# SINGLE EXTRACTION PASS
# ============================================================

def _extract_pass(
    device,
    disc,
    track_number,
    output_path,
    fast,
    read_offset_samples,
    cancel_event,
    progress_callback,
    process_callback,
):
    track = _find_track(
        disc,
        track_number,
    )

    expected_bytes = (
        _expected_track_bytes(
            track
        )
    )

    command = (
        _build_cdparanoia_command(
            device=device,
            track_number=
                track_number,
            output_path=
                output_path,
            fast=fast,
            read_offset_samples=
                read_offset_samples,
        )
    )

    _run_cdparanoia(
        command=
            command,
        output_path=
            output_path,
        expected_bytes=
            expected_bytes,
        cancel_event=
            cancel_event,
        progress_callback=
            progress_callback,
        process_callback=
            process_callback,
    )

    crc = (
        accuraterip
        .calculate_wav_crc(
            output_path,
            first_track=
                _is_first_track(
                    disc,
                    track_number,
                ),
            last_track=
                _is_last_track(
                    disc,
                    track_number,
                ),
        )
    )

    return {
        "wav_path":
            str(output_path),

        "crc":
            crc,

        "fast":
            bool(fast),
    }


# ============================================================
# ACCURATERIP VERIFICATION
# ============================================================

def _verify_pass(
    track_number,
    pass_result,
    accurate_rip_lookup,
):
    if not accurate_rip_lookup:
        return {
            "track_number":
                int(track_number),

            "database_available":
                False,

            "matched":
                False,

            "confidence":
                0,

            "pressing_count":
                0,

            "local_v1":
                pass_result[
                    "crc"
                ]["v1"],

            "local_v2":
                pass_result[
                    "crc"
                ]["v2"],

            "local_v1_text":
                pass_result[
                    "crc"
                ]["v1_text"],

            "local_v2_text":
                pass_result[
                    "crc"
                ]["v2_text"],

            "matched_crc":
                None,

            "matched_crc_text":
                None,
        }

    entries = (
        accurate_rip_lookup.get(
            "entries",
            [],
        )
    )

    return (
        accuraterip.verify_track(
            track_number=
                track_number,
            local_crc=
                pass_result[
                    "crc"
                ],
            database_entries=
                entries,
        )
    )


def _same_crc(
    first,
    second,
):
    return (
        first["crc"]["v1"]
        == second["crc"]["v1"]
        and
        first["crc"]["v2"]
        == second["crc"]["v2"]
    )


# ============================================================
# RIP TRACK
# ============================================================

def rip_track_to_wav(
    device,
    disc,
    track_number,
    output_path,
    rip_mode=RIP_MODE_AUTOMATIC,
    read_offset_samples=0,
    accurate_rip_lookup=None,
    cancel_event=None,
    progress_callback=None,
    status_callback=None,
    process_callback=None,
):
    """
    Rip one CD track to a final WAV.

    Behaviour:

    FAST
        One -Z extraction.
        AccurateRip is checked when available.
        The extraction is accepted regardless of AR result.

    AUTOMATIC
        First Fast (-Z) extraction.
        If AccurateRip confirms it: accept.
        Otherwise perform a second Fast extraction.

        If the second Fast extraction matches AccurateRip:
        accept it.

        If AccurateRip is unavailable/no disc entry but both
        Fast passes produce identical ARv1+ARv2 CRCs:
        accept the second pass.

        Otherwise fall back to cdparanoia's full verification/
        correction mode.

    SECURE
        Skip Fast passes and use cdparanoia's normal paranoia
        verification/correction mode.

    AccurateRip availability is NEVER required to complete a rip.
    """

    mode = _normalise_mode(
        rip_mode
    )

    track_number = int(
        track_number
    )

    output_path = Path(
        output_path
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    work_dir = (
        output_path.parent
        / (
            ".actuallyfreecd-"
            f"{track_number:02d}"
        )
    )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    first_fast_path = (
        work_dir
        / "fast1.wav"
    )

    second_fast_path = (
        work_dir
        / "fast2.wav"
    )

    secure_path = (
        work_dir
        / "secure.wav"
    )

    report = {
        "track_number":
            track_number,

        "requested_mode":
            mode,

        "actual_mode":
            None,

        "used_secure_fallback":
            False,

        "read_offset_samples":
            int(
                read_offset_samples
                or 0
            ),

        "accuraterip":
            None,

        "automatic_first_pass":
            None,

        "automatic_second_pass":
            None,

        "passes":
            [],
    }

    def status(text):
        if status_callback is not None:
            status_callback(
                text
            )

    try:

        # ====================================================
        # SECURE
        # ====================================================

        if mode == RIP_MODE_SECURE:

            status(
                f"Secure read of track "
                f"{track_number:02d}"
            )

            secure_result = (
                _extract_pass(
                    device=device,
                    disc=disc,
                    track_number=
                        track_number,
                    output_path=
                        secure_path,
                    fast=False,
                    read_offset_samples=
                        read_offset_samples,
                    cancel_event=
                        cancel_event,
                    progress_callback=
                        progress_callback,
                    process_callback=
                        process_callback,
                )
            )

            verification = (
                _verify_pass(
                    track_number,
                    secure_result,
                    accurate_rip_lookup,
                )
            )

            report["passes"].append(
                {
                    "name":
                        "secure",

                    "crc":
                        secure_result[
                            "crc"
                        ],

                    "verification":
                        verification,
                }
            )

            report[
                "actual_mode"
            ] = RIP_MODE_SECURE

            report[
                "accuraterip"
            ] = verification

            shutil.move(
                str(secure_path),
                str(output_path),
            )

            return report


        # ====================================================
        # FIRST FAST PASS
        # ====================================================

        status(
            f"Fast read 1 of track "
            f"{track_number:02d}"
        )

        first_fast = (
            _extract_pass(
                device=device,
                disc=disc,
                track_number=
                    track_number,
                output_path=
                    first_fast_path,
                fast=True,
                read_offset_samples=
                    read_offset_samples,
                cancel_event=
                    cancel_event,
                progress_callback=
                    progress_callback,
                process_callback=
                    process_callback,
            )
        )

        first_verification = (
            _verify_pass(
                track_number,
                first_fast,
                accurate_rip_lookup,
            )
        )

        first_report = {
            "crc":
                first_fast["crc"],

            "verification":
                first_verification,
        }

        report[
            "automatic_first_pass"
        ] = first_report

        report["passes"].append(
            {
                "name":
                    "fast1",

                **first_report,
            }
        )


        # ====================================================
        # EXPLICIT FAST
        # ====================================================

        if mode == RIP_MODE_FAST:

            report[
                "actual_mode"
            ] = RIP_MODE_FAST

            report[
                "accuraterip"
            ] = first_verification

            shutil.move(
                str(first_fast_path),
                str(output_path),
            )

            return report


        # ====================================================
        # AUTOMATIC — AR CONFIRMED FIRST FAST PASS
        # ====================================================

        if first_verification.get(
            "matched"
        ):

            report[
                "actual_mode"
            ] = RIP_MODE_FAST

            report[
                "accuraterip"
            ] = first_verification

            shutil.move(
                str(first_fast_path),
                str(output_path),
            )

            return report


        # ====================================================
        # SECOND FAST PASS
        # ====================================================

        status(
            f"Fast read 2 of track "
            f"{track_number:02d}"
        )

        if progress_callback is not None:
            progress_callback(
                0.0
            )

        second_fast = (
            _extract_pass(
                device=device,
                disc=disc,
                track_number=
                    track_number,
                output_path=
                    second_fast_path,
                fast=True,
                read_offset_samples=
                    read_offset_samples,
                cancel_event=
                    cancel_event,
                progress_callback=
                    progress_callback,
                process_callback=
                    process_callback,
            )
        )

        second_verification = (
            _verify_pass(
                track_number,
                second_fast,
                accurate_rip_lookup,
            )
        )

        second_report = {
            "crc":
                second_fast["crc"],

            "verification":
                second_verification,
        }

        report[
            "automatic_second_pass"
        ] = second_report

        report["passes"].append(
            {
                "name":
                    "fast2",

                **second_report,
            }
        )


        # ====================================================
        # AR CONFIRMED SECOND FAST PASS
        # ====================================================

        if second_verification.get(
            "matched"
        ):

            report[
                "actual_mode"
            ] = RIP_MODE_FAST

            report[
                "accuraterip"
            ] = second_verification

            shutil.move(
                str(second_fast_path),
                str(output_path),
            )

            return report


        # ====================================================
        # ACCURATERIP UNAVAILABLE / DISC NOT IN DATABASE
        #
        # Do not make AR a requirement. If two independent Fast
        # passes produce identical audio CRCs, accept the result.
        # ====================================================

        ar_has_entries = bool(
            accurate_rip_lookup
            and accurate_rip_lookup.get(
                "found",
                False,
            )
        )

        if (
            not ar_has_entries
            and _same_crc(
                first_fast,
                second_fast,
            )
        ):

            report[
                "actual_mode"
            ] = RIP_MODE_FAST

            report[
                "accuraterip"
            ] = second_verification

            report[
                "verified_by_second_read"
            ] = True

            shutil.move(
                str(second_fast_path),
                str(output_path),
            )

            return report


        # ====================================================
        # SECURE FALLBACK
        # ====================================================

        status(
            f"Secure fallback for track "
            f"{track_number:02d}"
        )

        if progress_callback is not None:
            progress_callback(
                0.0
            )

        secure_result = (
            _extract_pass(
                device=device,
                disc=disc,
                track_number=
                    track_number,
                output_path=
                    secure_path,
                fast=False,
                read_offset_samples=
                    read_offset_samples,
                cancel_event=
                    cancel_event,
                progress_callback=
                    progress_callback,
                process_callback=
                    process_callback,
            )
        )

        secure_verification = (
            _verify_pass(
                track_number,
                secure_result,
                accurate_rip_lookup,
            )
        )

        report["passes"].append(
            {
                "name":
                    "secure_fallback",

                "crc":
                    secure_result[
                        "crc"
                    ],

                "verification":
                    secure_verification,
            }
        )

        report[
            "actual_mode"
        ] = RIP_MODE_SECURE

        report[
            "used_secure_fallback"
        ] = True

        report[
            "accuraterip"
        ] = secure_verification

        shutil.move(
            str(secure_path),
            str(output_path),
        )

        return report

    finally:

        _safe_unlink(
            first_fast_path
        )

        _safe_unlink(
            second_fast_path
        )

        _safe_unlink(
            secure_path
        )

        try:
            work_dir.rmdir()
        except Exception:
            pass


# ============================================================
# STATUS TEXT
# ============================================================

def result_status_text(
    report,
    accurate_rip_lookup=None,
):
    verification = (
        report.get(
            "accuraterip"
        )
        or {}
    )

    if verification.get(
        "matched"
    ):
        return (
            "AccurateRip ✓ "
            f"(confidence "
            f"{verification.get('confidence', 0)})"
        )

    if report.get(
        "verified_by_second_read"
    ):
        return (
            "Verified by second read"
        )

    if (
        accurate_rip_lookup is not None
        and not accurate_rip_lookup.get(
            "available",
            False,
        )
    ):
        return (
            "AR unavailable"
        )

    if (
        accurate_rip_lookup is not None
        and not accurate_rip_lookup.get(
            "found",
            False,
        )
    ):
        return (
            "AR no entry"
        )

    if report.get(
        "used_secure_fallback"
    ):
        return (
            "Secure fallback"
        )

    return (
        "AR no match"
    )