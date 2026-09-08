# ActuallyFreeCD Server

ActuallyFreeCD Server is a free, server-based audio CD ripping application with a web interface. CDs are read, ripped, verified, and encoded directly on the server, so an active rip continues even if the browser disconnects.

## Features

- FLAC and MP3 encoding
- Fast, Automatic, and Secure ripping modes
- MusicBrainz metadata lookup
- CD-Text metadata
- Manual metadata editing
- Album artwork lookup
- AccurateRip verification
- Drive offset support
- Persistent rip logs
- Browser reconnection to active rip sessions
- Optical drive eject control
- Output ownership and permission controls for shared storage

## Container Image

The current container image is:

```text
ghcr.io/d69wookie/actuallyfreecd-server:0.9.0
```

The application listens on port:

```text
8080
```

## Required Storage

ActuallyFreeCD Server writes ripped music and application data beneath:

```text
/music
```

Map a persistent host dataset or directory to `/music`.

Example:

```yaml
volumes:
  - /mnt/tank/music:/music
```

## Optical Drive Access

ActuallyFreeCD Server requires access to both Linux device nodes associated with the optical drive:

- the optical block device, for example `/dev/sr0`
- the matching SCSI generic device, for example `/dev/sg8`

On TrueNAS or another Linux host, identify the matching device pair with:

```bash
lsscsi -g
```

A typical optical drive may use:

```text
/dev/sr0
/dev/sg8
```

Both devices should be passed into the container beneath `/hostdev`:

```yaml
devices:
  - /dev/sr0:/hostdev/sr0
  - /dev/sg8:/hostdev/sg8
```

ActuallyFreeCD Server uses `/sys` information to correlate the optical block device with its matching SCSI generic device.

## Environment Variables

| Variable | Purpose | Typical Value |
| --- | --- | --- |
| `DEVICE_ROOT` | Root path used for passed-through optical devices | `/hostdev` |
| `MUSIC_ROOT` | Music output path inside the container | `/music` |
| `AFCD_OUTPUT_UID` | Optional UID to apply to created output files | host/user UID |
| `AFCD_OUTPUT_GID` | Optional GID to apply to created output files | shared media GID |
| `AFCD_DIR_MODE` | Permissions for newly created directories | `0775` |
| `AFCD_FILE_MODE` | Permissions for newly created files | `0664` |

If `AFCD_OUTPUT_UID` or `AFCD_OUTPUT_GID` is not required, it can be omitted.

## Example Docker Compose

```yaml
services:
  actuallyfreecd:
    image: ghcr.io/d69wookie/actuallyfreecd-server:0.9.0
    container_name: actuallyfreecd
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      DEVICE_ROOT: /hostdev
      MUSIC_ROOT: /music
      AFCD_DIR_MODE: "0775"
      AFCD_FILE_MODE: "0664"
    devices:
      - /dev/sr0:/hostdev/sr0
      - /dev/sg8:/hostdev/sg8
    volumes:
      - /mnt/tank/music:/music
```

Adjust the storage path and optical device names for your system.

## TrueNAS Notes

When installing ActuallyFreeCD Server on TrueNAS:

1. Select persistent storage for the `/music` path.
2. Identify the optical drive and matching SCSI generic device using `lsscsi -g`.
3. Pass both devices into the container.
4. Map the host devices beneath `/hostdev`.
5. If the music dataset is also used by SMB, Plex, or other applications, configure `AFCD_OUTPUT_GID` to match the shared media group if required.
6. Choose directory and file modes that suit the permissions on the destination dataset.

For example, a shared media setup may use:

```text
AFCD_OUTPUT_GID=3001
AFCD_DIR_MODE=2775
AFCD_FILE_MODE=0664
```

Use values appropriate for your own TrueNAS permissions and dataset ACLs.

## Metadata

ActuallyFreeCD Server supports:

- MusicBrainz
- CD-Text
- Manual metadata entry

MusicBrainz and artwork lookup require internet access. CD-Text and manual metadata entry can still be used without MusicBrainz.

## AccurateRip

ActuallyFreeCD Server can verify ripped audio against AccurateRip when a matching disc is available in the AccurateRip database.

AccurateRip verification requires internet access.

## Browser Access

After the container starts, open:

```text
http://<server-ip>:8080
```

If a different host port is mapped to container port `8080`, use that host port instead.

## Releases

Project releases are published here:

https://github.com/D69wookie/ActuallyFreeCD-Server/releases

## Source

Source code:

https://github.com/D69wookie/ActuallyFreeCD-Server

## Licence and Third-Party Notices

See the repository's licence information and `THIRD_PARTY_NOTICES.txt` for applicable third-party software notices.
