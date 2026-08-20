import struct
import urllib.error
import urllib.request


USER_AGENT = (
    "ActuallyFreeCD-Server/0.7 "
    "(wookiesoft+actuallyfreeCD@gmail.com)"
)

ACCURATERIP_BASE_URL = (
    "http://www.accuraterip.com/accuraterip"
)

HTTP_TIMEOUT_SECONDS = 20

CD_AUDIO_SECTOR_SIZE = 2352
SAMPLES_PER_SECTOR = 588
BYTES_PER_SAMPLE_FRAME = 4


# ============================================================
# DISC ID
# ============================================================

def calculate_disc_id(disc):
    """
    Calculate the AccurateRip Disc ID from the disc TOC.

    The Linux drive-discovery code stores track start_sector
    values with Track 1 normally beginning at sector 0.

    We still subtract Track 1's start sector so this remains
    correct if a future drive/parser reports a non-zero base.
    """

    tracks = disc.get(
        "tracks",
        [],
    )

    if not tracks:
        raise ValueError(
            "Disc has no audio tracks."
        )

    base_offset = int(
        tracks[0].get(
            "start_sector",
            0,
        )
    )

    offsets = [
        int(
            track.get(
                "start_sector",
                0,
            )
        )
        - base_offset
        for track in tracks
    ]

    last_track = tracks[-1]

    leadout = (
        int(
            last_track.get(
                "start_sector",
                0,
            )
        )
        + int(
            last_track.get(
                "sectors",
                0,
            )
        )
        - base_offset
    )

    # --------------------------------------------------------
    # AccurateRip Disc ID 1
    # --------------------------------------------------------

    disc_id_1 = (
        sum(offsets)
        + leadout
    ) & 0xFFFFFFFF

    # --------------------------------------------------------
    # AccurateRip Disc ID 2
    # --------------------------------------------------------

    disc_id_2 = 0

    for index, offset in enumerate(
        offsets,
        start=1,
    ):
        value = (
            1
            if offset == 0
            else offset
        )

        disc_id_2 += (
            value
            * index
        )

    disc_id_2 += (
        leadout
        * (
            len(offsets)
            + 1
        )
    )

    disc_id_2 &= 0xFFFFFFFF

    # --------------------------------------------------------
    # CDDB Disc ID
    # --------------------------------------------------------

    digit_sum = 0

    for offset in offsets:

        seconds = (
            offset
            + 150
        ) // 75

        while seconds > 0:

            digit_sum += (
                seconds
                % 10
            )

            seconds //= 10

    total_seconds = (
        (
            leadout
            + 150
        )
        // 75
    ) - (
        (
            offsets[0]
            + 150
        )
        // 75
    )

    cddb_disc_id = (
        (
            digit_sum
            % 255
        )
        << 24
    ) | (
        (
            total_seconds
            & 0xFFFF
        )
        << 8
    ) | (
        len(offsets)
        & 0xFF
    )

    cddb_disc_id &= (
        0xFFFFFFFF
    )

    result = {
        "disc_id_1":
            disc_id_1,

        "disc_id_2":
            disc_id_2,

        "cddb_disc_id":
            cddb_disc_id,

        "track_count":
            len(offsets),

        "disc_id_1_text":
            f"{disc_id_1:08x}",

        "disc_id_2_text":
            f"{disc_id_2:08x}",

        "cddb_text":
            f"{cddb_disc_id:08x}",
    }

    result["database_url"] = (
        build_database_url(
            result
        )
    )

    return result


def build_database_url(
    disc_id
):
    """
    Construct the standard AccurateRip database path.
    """

    id1 = (
        disc_id[
            "disc_id_1_text"
        ]
    )

    a = id1[7]
    b = id1[6]
    c = id1[5]

    return (
        f"{ACCURATERIP_BASE_URL}/"
        f"{a}/{b}/{c}/"
        f"dBAR-"
        f"{disc_id['track_count']:03d}-"
        f"{disc_id['disc_id_1_text']}-"
        f"{disc_id['disc_id_2_text']}-"
        f"{disc_id['cddb_text']}.bin"
    )


# ============================================================
# DATABASE LOOKUP
# ============================================================

def query_database(
    disc
):
    """
    Query AccurateRip.

    This function deliberately does NOT make AccurateRip
    availability a ripping requirement.

    Return format:

        {
            "available": True/False,
            "found": True/False,
            "entries": [...],
            "disc_id": {...},
            "error": None or text
        }

    A missing database entry, network failure, timeout or
    AccurateRip service failure can therefore be reported
    without preventing ActuallyFreeCD from ripping the disc.
    """

    disc_id = calculate_disc_id(
        disc
    )

    database_url = (
        disc_id[
            "database_url"
        ]
    )

    request = (
        urllib.request.Request(
            database_url,
            headers={
                "User-Agent":
                    USER_AGENT,
            },
        )
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=
                HTTP_TIMEOUT_SECONDS,
        ) as response:

            data = (
                response.read()
            )

        entries = parse_database(
            data
        )

        return {
            "available":
                True,

            "found":
                bool(entries),

            "entries":
                entries,

            "disc_id":
                disc_id,

            "error":
                None,
        }

    except urllib.error.HTTPError as exc:

        if exc.code == 404:

            return {
                "available":
                    True,

                "found":
                    False,

                "entries":
                    [],

                "disc_id":
                    disc_id,

                "error":
                    None,
            }

        return {
            "available":
                False,

            "found":
                False,

            "entries":
                [],

            "disc_id":
                disc_id,

            "error":
                (
                    "AccurateRip lookup "
                    f"returned HTTP "
                    f"{exc.code}"
                ),
        }

    except urllib.error.URLError as exc:

        return {
            "available":
                False,

            "found":
                False,

            "entries":
                [],

            "disc_id":
                disc_id,

            "error":
                (
                    "AccurateRip is "
                    "unavailable: "
                    f"{exc.reason}"
                ),
        }

    except TimeoutError:

        return {
            "available":
                False,

            "found":
                False,

            "entries":
                [],

            "disc_id":
                disc_id,

            "error":
                (
                    "AccurateRip lookup "
                    "timed out"
                ),
        }

    except Exception as exc:

        return {
            "available":
                False,

            "found":
                False,

            "entries":
                [],

            "disc_id":
                disc_id,

            "error":
                str(exc),
        }


# ============================================================
# DATABASE PARSING
# ============================================================

def parse_database(
    data
):
    """
    Parse the AccurateRip binary database format used by the
    existing ActuallyFreeCD Windows implementation.

    Each pressing begins with:

        1 byte   track count
        4 bytes  Disc ID 1
        4 bytes  Disc ID 2
        4 bytes  CDDB ID

    followed by 9 bytes for every track:

        1 byte   confidence
        4 bytes  primary CRC
        4 bytes  frame-450 CRC
    """

    entries = []

    offset = 0
    data_length = len(
        data
    )

    while (
        offset + 13
        <= data_length
    ):

        track_count = (
            data[offset]
        )

        offset += 1

        if (
            offset + 12
            > data_length
        ):
            break

        disc_id_1 = (
            struct.unpack_from(
                "<I",
                data,
                offset,
            )[0]
        )

        offset += 4

        disc_id_2 = (
            struct.unpack_from(
                "<I",
                data,
                offset,
            )[0]
        )

        offset += 4

        cddb_disc_id = (
            struct.unpack_from(
                "<I",
                data,
                offset,
            )[0]
        )

        offset += 4

        required = (
            track_count
            * 9
        )

        if (
            offset + required
            > data_length
        ):
            break

        for track_number in range(
            1,
            track_count + 1,
        ):

            confidence = (
                data[offset]
            )

            offset += 1

            crc = (
                struct.unpack_from(
                    "<I",
                    data,
                    offset,
                )[0]
            )

            offset += 4

            frame450_crc = (
                struct.unpack_from(
                    "<I",
                    data,
                    offset,
                )[0]
            )

            offset += 4

            entries.append({
                "track_number":
                    track_number,

                "confidence":
                    confidence,

                "crc":
                    crc,

                "crc_text":
                    f"{crc:08X}",

                "frame450_crc":
                    frame450_crc,

                "frame450_crc_text":
                    f"{frame450_crc:08X}",

                "disc_id_1":
                    disc_id_1,

                "disc_id_2":
                    disc_id_2,

                "cddb_disc_id":
                    cddb_disc_id,
            })

    return entries


# ============================================================
# WAV / PCM READING
# ============================================================

def read_wav_pcm(
    wav_path
):
    """
    Read PCM audio from a standard 16-bit stereo 44.1 kHz WAV.

    cdparanoia produces this format for the files used by the
    Linux ActuallyFreeCD ripping path.

    This parser walks RIFF chunks instead of assuming that the
    audio data always begins at byte 44.
    """

    with open(
        wav_path,
        "rb",
    ) as file:

        riff_header = (
            file.read(12)
        )

        if len(riff_header) != 12:

            raise ValueError(
                "Invalid WAV file."
            )

        if (
            riff_header[0:4]
            != b"RIFF"
            or
            riff_header[8:12]
            != b"WAVE"
        ):

            raise ValueError(
                "File is not a RIFF/WAVE file."
            )

        format_info = None
        pcm_data = None

        while True:

            chunk_header = (
                file.read(8)
            )

            if not chunk_header:
                break

            if len(chunk_header) != 8:

                raise ValueError(
                    "Invalid WAV chunk."
                )

            chunk_id = (
                chunk_header[0:4]
            )

            chunk_size = (
                struct.unpack(
                    "<I",
                    chunk_header[4:8],
                )[0]
            )

            chunk_data = (
                file.read(
                    chunk_size
                )
            )

            if (
                len(chunk_data)
                != chunk_size
            ):

                raise ValueError(
                    "Incomplete WAV chunk."
                )

            # RIFF chunks are padded to an even number of bytes.
            if chunk_size & 1:
                file.read(1)

            if (
                chunk_id
                == b"fmt "
            ):

                if chunk_size < 16:

                    raise ValueError(
                        "Invalid WAV format chunk."
                    )

                (
                    audio_format,
                    channels,
                    sample_rate,
                    _byte_rate,
                    block_align,
                    bits_per_sample,
                ) = struct.unpack_from(
                    "<HHIIHH",
                    chunk_data,
                    0,
                )

                format_info = {
                    "audio_format":
                        audio_format,

                    "channels":
                        channels,

                    "sample_rate":
                        sample_rate,

                    "block_align":
                        block_align,

                    "bits_per_sample":
                        bits_per_sample,
                }

            elif (
                chunk_id
                == b"data"
            ):

                pcm_data = (
                    chunk_data
                )

        if format_info is None:

            raise ValueError(
                "WAV format chunk not found."
            )

        if pcm_data is None:

            raise ValueError(
                "WAV audio data not found."
            )

        if (
            format_info[
                "audio_format"
            ]
            != 1
        ):

            raise ValueError(
                "WAV is not PCM audio."
            )

        if (
            format_info[
                "channels"
            ]
            != 2
        ):

            raise ValueError(
                "WAV is not stereo audio."
            )

        if (
            format_info[
                "sample_rate"
            ]
            != 44100
        ):

            raise ValueError(
                "WAV is not 44.1 kHz audio."
            )

        if (
            format_info[
                "bits_per_sample"
            ]
            != 16
        ):

            raise ValueError(
                "WAV is not 16-bit audio."
            )

        if (
            format_info[
                "block_align"
            ]
            != BYTES_PER_SAMPLE_FRAME
        ):

            raise ValueError(
                "Unexpected WAV block alignment."
            )

        return pcm_data


# ============================================================
# ACCURATERIP CRC
# ============================================================

def calculate_track_crc(
    pcm,
    first_track=False,
    last_track=False,
):
    """
    Calculate AccurateRip v1 and v2 CRCs.

    This mirrors CdAudioRipper.CalculateAccurateRip() from the
    Windows ActuallyFreeCD implementation.

    'pcm' must contain offset-corrected CD audio:
        stereo
        16-bit
        44.1 kHz
        little-endian
    """

    if (
        len(pcm)
        % BYTES_PER_SAMPLE_FRAME
        != 0
    ):

        raise ValueError(
            "PCM data is not aligned "
            "to stereo sample frames."
        )

    total_samples = (
        len(pcm)
        // BYTES_PER_SAMPLE_FRAME
    )

    first_position = (
        5
        * SAMPLES_PER_SECTOR
        if first_track
        else 1
    )

    last_position = (
        total_samples
        - (
            5
            * SAMPLES_PER_SECTOR
            if last_track
            else 0
        )
    )

    if (
        last_position
        < first_position
    ):

        raise ValueError(
            "Track is too short "
            "for AccurateRip calculation."
        )

    arv1 = 0
    arv2 = 0

    for position in range(
        first_position,
        last_position + 1,
    ):

        byte_offset = (
            position - 1
        ) * BYTES_PER_SAMPLE_FRAME

        value = (
            struct.unpack_from(
                "<I",
                pcm,
                byte_offset,
            )[0]
        )

        product = (
            position
            * value
        )

        # Match C# unchecked uint overflow.
        arv1 = (
            arv1
            + (
                product
                & 0xFFFFFFFF
            )
        ) & 0xFFFFFFFF

        arv2 = (
            arv2
            + (
                product
                & 0xFFFFFFFF
            )
            + (
                (
                    product
                    >> 32
                )
                & 0xFFFFFFFF
            )
        ) & 0xFFFFFFFF

    return {
        "v1":
            arv1,

        "v2":
            arv2,

        "v1_text":
            f"{arv1:08X}",

        "v2_text":
            f"{arv2:08X}",
    }


def calculate_wav_crc(
    wav_path,
    first_track=False,
    last_track=False,
):
    """
    Convenience wrapper for a WAV produced by cdparanoia.
    """

    pcm = read_wav_pcm(
        wav_path
    )

    return calculate_track_crc(
        pcm,
        first_track=
            first_track,
        last_track=
            last_track,
    )


# ============================================================
# TRACK VERIFICATION
# ============================================================

def verify_track(
    track_number,
    local_crc,
    database_entries,
):
    """
    Compare a local ARv1/ARv2 result against every AccurateRip
    pressing entry for this track.

    As with the Windows version, the AccurateRip primary CRC is
    compared against BOTH ARv1 and ARv2.
    """

    track_number = int(
        track_number
    )

    candidates = [
        entry
        for entry in database_entries
        if int(
            entry[
                "track_number"
            ]
        )
        == track_number
    ]

    if not candidates:

        return {
            "track_number":
                track_number,

            "database_available":
                bool(
                    database_entries
                ),

            "matched":
                False,

            "confidence":
                0,

            "matched_crc":
                None,

            "matched_crc_text":
                None,

            "pressing_count":
                0,

            "local_v1":
                local_crc["v1"],

            "local_v2":
                local_crc["v2"],

            "local_v1_text":
                local_crc[
                    "v1_text"
                ],

            "local_v2_text":
                local_crc[
                    "v2_text"
                ],
        }

    matches = [
        entry
        for entry in candidates
        if (
            entry["crc"]
            == local_crc["v1"]
            or
            entry["crc"]
            == local_crc["v2"]
        )
    ]

    if matches:

        best_match = max(
            matches,
            key=lambda entry:
                entry[
                    "confidence"
                ],
        )

        return {
            "track_number":
                track_number,

            "database_available":
                True,

            "matched":
                True,

            "confidence":
                int(
                    best_match[
                        "confidence"
                    ]
                ),

            "matched_crc":
                best_match[
                    "crc"
                ],

            "matched_crc_text":
                best_match[
                    "crc_text"
                ],

            "pressing_count":
                len(
                    candidates
                ),

            "local_v1":
                local_crc["v1"],

            "local_v2":
                local_crc["v2"],

            "local_v1_text":
                local_crc[
                    "v1_text"
                ],

            "local_v2_text":
                local_crc[
                    "v2_text"
                ],
        }

    return {
        "track_number":
            track_number,

        "database_available":
            True,

        "matched":
            False,

        "confidence":
            0,

        "matched_crc":
            None,

        "matched_crc_text":
            None,

        "pressing_count":
            len(
                candidates
            ),

        "local_v1":
            local_crc["v1"],

        "local_v2":
            local_crc["v2"],

        "local_v1_text":
            local_crc[
                "v1_text"
            ],

        "local_v2_text":
            local_crc[
                "v2_text"
            ],
    }


# ============================================================
# DISPLAY HELPERS
# ============================================================

def verification_status_text(
    verification,
    lookup=None,
):
    """
    Produce the short status text that will eventually appear
    in the ActuallyFreeCD track grid.
    """

    if (
        lookup is not None
        and not lookup.get(
            "available",
            False,
        )
    ):

        return (
            "AR unavailable"
        )

    if verification.get(
        "matched"
    ):

        confidence = int(
            verification.get(
                "confidence",
                0,
            )
        )

        return (
            "AccurateRip ✓ "
            f"(confidence {confidence})"
        )

    if not verification.get(
        "database_available"
    ):

        return (
            "AR no entry"
        )

    return (
        "AR no match"
    )