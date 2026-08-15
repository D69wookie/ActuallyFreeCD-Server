from musicbrainz import calculate_disc_id


# Known TOC captured from the test CD in the Optiarc AD-7561S.
TEST_TRACKS = [
    {"number": 1,  "start_sector": 0,      "sectors": 28803},
    {"number": 2,  "start_sector": 28803,  "sectors": 30813},
    {"number": 3,  "start_sector": 59616,  "sectors": 27080},
    {"number": 4,  "start_sector": 86696,  "sectors": 31541},
    {"number": 5,  "start_sector": 118237, "sectors": 29785},
    {"number": 6,  "start_sector": 148022, "sectors": 29019},
    {"number": 7,  "start_sector": 177041, "sectors": 32430},
    {"number": 8,  "start_sector": 209471, "sectors": 33501},
    {"number": 9,  "start_sector": 242972, "sectors": 28216},
    {"number": 10, "start_sector": 271188, "sectors": 30419},
    {"number": 11, "start_sector": 301607, "sectors": 27323},
    {"number": 12, "start_sector": 328930, "sectors": 22766},
]


def main():
    result = calculate_disc_id(TEST_TRACKS)

    print()
    print("ActuallyFreeCD - MusicBrainz Disc ID Test")
    print("==========================================")
    print()

    if not result:
        print("ERROR: Disc ID calculation failed.")
        return

    print(f"Disc ID:     {result['disc_id']}")
    print(f"First track: {result['first_track']}")
    print(f"Last track:  {result['last_track']}")
    print(f"Lead-out:    {result['leadout']}")
    print()

    print("MusicBrainz track offsets:")
    for number, offset in enumerate(
        result["offsets"],
        start=result["first_track"],
    ):
        print(f"  Track {number:02d}: {offset}")


if __name__ == "__main__":
    main()