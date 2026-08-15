import json
import urllib.parse
import urllib.request
import urllib.error

from musicbrainz import calculate_disc_id


USER_AGENT = (
    "ActuallyFreeCD/0.4 "
    "(wookiesoft+actuallyfreeCD@gmail.com)"
)


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


def build_toc(result):
    values = [
        result["first_track"],
        result["last_track"],
        result["leadout"],
    ]

    values.extend(result["offsets"])

    return " ".join(str(value) for value in values)


def lookup_musicbrainz(disc_id, toc):
    params = urllib.parse.urlencode({
        "toc": toc,
        "inc": "recordings+artist-credits+release-groups",
        "cdstubs": "no",
        "fmt": "json",
    })

    url = (
        "https://musicbrainz.org/ws/2/discid/"
        + urllib.parse.quote(disc_id)
        + "?"
        + params
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def artist_credit_text(artist_credit):
    parts = []

    for credit in artist_credit or []:
        if isinstance(credit, str):
            parts.append(credit)
            continue

        parts.append(credit.get("name", ""))

        joinphrase = credit.get("joinphrase")

        if joinphrase:
            parts.append(joinphrase)

    return "".join(parts)


def main():
    disc = calculate_disc_id(TEST_TRACKS)

    if not disc:
        print("ERROR: Unable to calculate Disc ID.")
        return

    disc_id = disc["disc_id"]
    toc = build_toc(disc)

    print()
    print("ActuallyFreeCD - MusicBrainz Lookup Test")
    print("========================================")
    print()
    print(f"Disc ID: {disc_id}")
    print(f"TOC:     {toc}")
    print()
    print("Contacting MusicBrainz...")
    print()

    try:
        result = lookup_musicbrainz(disc_id, toc)

    except urllib.error.HTTPError as exc:
        print(f"MusicBrainz returned HTTP {exc.code}")

        try:
            print(exc.read().decode("utf-8"))
        except Exception:
            pass

        return

    except Exception as exc:
        print(f"Lookup failed: {exc}")
        return

    releases = result.get("releases", [])

    print(f"Releases returned: {len(releases)}")
    print()

    if not releases:
        print("No matching releases were returned.")
        return

    for index, release in enumerate(releases, start=1):
        artist = artist_credit_text(
            release.get("artist-credit", [])
        )

        print(f"Result {index}")
        print(f"  Artist:  {artist}")
        print(f"  Album:   {release.get('title', 'Unknown')}")

        if release.get("date"):
            print(f"  Date:    {release['date']}")

        if release.get("country"):
            print(f"  Country: {release['country']}")

        if release.get("status"):
            print(f"  Status:  {release['status']}")

        if release.get("barcode"):
            print(f"  Barcode: {release['barcode']}")

        print(f"  MBID:    {release.get('id', '')}")

        for medium in release.get("media", []):
            print(
                f"  Medium:  {medium.get('position')} "
                f"({medium.get('track-count')} tracks)"
            )

            for track in medium.get("tracks", []):
                number = track.get("number", "")
                title = track.get("title", "")

                print(f"      {number:>2}. {title}")

        print()


if __name__ == "__main__":
    main()