from pathlib import Path
import os
import re
import subprocess


# Where the container can see host device nodes.
# TrueNAS will use /hostdev.
# /dev remains the default for conventional Linux installations.
DEVICE_ROOT = Path(os.environ.get("DEVICE_ROOT", "/dev"))


def read_text(path):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def get_serial(sr_name):
    """
    Retrieve the hardware serial from sysfs.

    We deliberately use sysfs rather than relying on the host udev
    database, because that database may not be available inside
    the container.
    """
    try:
        sys_device = Path("/sys/class/block") / sr_name

        result = subprocess.run(
            [
                "udevadm",
                "info",
                "--attribute-walk",
                f"--path={sys_device.resolve()}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        for line in result.stdout.splitlines():
            line = line.strip()

            if line.startswith('ATTRS{serial}=='):
                return line.split("==", 1)[1].strip().strip('"')

    except Exception:
        pass

    return None


def get_sg_name(sr_path):
    """
    Resolve the SCSI-generic device associated with an sr device.

    Example:
        sr0 -> sg8
    """
    try:
        sg_dir = sr_path / "device" / "scsi_generic"

        if not sg_dir.exists():
            return None

        sg_nodes = sorted(sg_dir.glob("sg*"))

        if not sg_nodes:
            return None

        return sg_nodes[0].name

    except Exception:
        return None

def get_disc_info(device_path):
    """
    Ask cdparanoia for the audio CD table of contents.
    """
    empty_disc = {
        "present": False,
        "audio": False,
        "track_count": 0,
        "length": None,
        "tracks": [],
    }

    try:
        result = subprocess.run(
            [
                "cdparanoia",
                "-d",
                str(device_path),
                "-Q",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        # cdparanoia writes its TOC information primarily to stderr.
        output = result.stdout + "\n" + result.stderr

        if "Table of contents (audio tracks only)" not in output:
            return empty_disc

        tracks = []

        track_pattern = re.compile(
            r"^\s*(\d+)\.\s+(\d+)\s+\[(\d+):(\d+)\.(\d+)\]\s+"
            r"(\d+)\s+\[(\d+):(\d+)\.(\d+)\]",
            re.MULTILINE,
        )

        for match in track_pattern.finditer(output):
            number = int(match.group(1))
            sectors = int(match.group(2))

            minutes = int(match.group(3))
            seconds = int(match.group(4))
            frames = int(match.group(5))

            start_sector = int(match.group(6))

            tracks.append({
                "number": number,
                "sectors": sectors,
                "start_sector": start_sector,
                "minutes": minutes,
                "seconds": seconds,
                "frames": frames,
                "length": f"{minutes:02d}:{seconds:02d}",
            })

        total_length = None

        total_match = re.search(
            r"TOTAL\s+\d+\s+\[(\d+):(\d+)\.(\d+)\]",
            output,
        )

        if total_match:
            total_minutes = int(total_match.group(1))
            total_seconds = int(total_match.group(2))

            total_length = f"{total_minutes:02d}:{total_seconds:02d}"

        return {
            "present": True,
            "audio": True,
            "track_count": len(tracks),
            "length": total_length,
            "tracks": tracks,
        }

    except subprocess.TimeoutExpired:
        return {
            **empty_disc,
            "error": "Timed out while reading disc",
        }

    except Exception as exc:
        return {
            **empty_disc,
            "error": str(exc),
        }



def find_cd_drives():
    drives = []

    sys_block = Path("/sys/class/block")

    if not sys_block.exists():
        return drives

    # Discover optical drives dynamically from sysfs.
    for sr_path in sorted(sys_block.glob("sr*")):
        sr_name = sr_path.name

        # The actual device node may live somewhere other than /dev.
        # On TrueNAS we expose the host's /dev as /hostdev.
        device_path = DEVICE_ROOT / sr_name

        # Ignore devices for which we cannot see a usable device node.
        if not device_path.exists():
            continue

        vendor = read_text(sr_path / "device" / "vendor")
        model = read_text(sr_path / "device" / "model")
        revision = read_text(sr_path / "device" / "rev")

        serial = get_serial(sr_name)

        sg_name = get_sg_name(sr_path)
        sg_device = (
            str(DEVICE_ROOT / sg_name)
            if sg_name
            else None
        )

        drive = {
            "id": serial or sr_name,
            "vendor": vendor,
            "model": model,
            "revision": revision,
            "serial": serial,

            # Current Linux addresses. These are deliberately not
            # treated as persistent drive identifiers.
            "device": str(device_path),
            "sg_device": sg_device,

            "disc": get_disc_info(device_path),
        }

        drives.append(drive)

    return drives


if __name__ == "__main__":
    print("ActuallyFreeCD drive discovery")
    print(f"Device root: {DEVICE_ROOT}")
    print()

    drives = find_cd_drives()

    if not drives:
        print("No optical drives found.")

    for index, drive in enumerate(drives, start=1):
        print(f"Drive {index}")
        print(f"  Vendor:    {drive['vendor']}")
        print(f"  Model:     {drive['model']}")
        print(f"  Revision:  {drive['revision']}")
        print(f"  Serial:    {drive['serial']}")
        print(f"  Device:    {drive['device']}")
        print(f"  SG Device: {drive['sg_device']}")

        disc = drive["disc"]

        if disc["present"] and disc["audio"]:
            print("  Disc:      Audio CD")
            print(f"  Tracks:    {disc['track_count']}")
            print(f"  Length:    {disc['length']}")

            for track in disc["tracks"]:
                print(
                    f"    Track {track['number']:02d}: "
                    f"{track['length']}"
                )
        else:
            print("  Disc:      No readable audio CD")

        print()