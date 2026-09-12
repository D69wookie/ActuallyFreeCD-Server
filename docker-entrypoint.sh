#!/bin/sh
set -eu

APP_UID="${USER_ID:-568}"
APP_GID="${GROUP_ID:-568}"
APP_USER="app"
APP_GROUP="app"
DEVICE_ROOT="${DEVICE_ROOT:-/hostdev}"
APP_UMASK="${UMASK:-002}"

if [ "$(id -u)" -ne 0 ]; then
    umask "${APP_UMASK}"
    echo "[AFCD init] Container is not running as root; launching command unchanged."
    exec "$@"
fi

echo "[AFCD init] Requested application identity: ${APP_UID}:${APP_GID}"
echo "[AFCD init] Applying umask: ${APP_UMASK}"

# Create or reuse the primary group.
existing_group="$(getent group "${APP_GID}" | cut -d: -f1 || true)"
if [ -n "${existing_group}" ]; then
    APP_GROUP="${existing_group}"
else
    groupadd -g "${APP_GID}" "${APP_GROUP}"
fi

# Create or reuse the application user.
existing_user="$(getent passwd "${APP_UID}" | cut -d: -f1 || true)"
if [ -n "${existing_user}" ]; then
    APP_USER="${existing_user}"
else
    useradd \
        --uid "${APP_UID}" \
        --gid "${APP_GID}" \
        --no-create-home \
        --home-dir /app \
        --shell /usr/sbin/nologin \
        "${APP_USER}"
fi

# Add the application user to each non-root group that owns an exposed
# block/character device under DEVICE_ROOT.
if [ -d "${DEVICE_ROOT}" ]; then
    for dev in "${DEVICE_ROOT}"/*; do
        [ -e "${dev}" ] || continue

        if [ -b "${dev}" ] || [ -c "${dev}" ]; then
            dev_gid="$(stat -c '%g' "${dev}")"
            dev_mode="$(stat -c '%a' "${dev}")"

            if [ "${dev_gid}" -ne 0 ]; then
                dev_group="$(getent group "${dev_gid}" | cut -d: -f1 || true)"

                if [ -z "${dev_group}" ]; then
                    dev_group="afcddev${dev_gid}"
                    groupadd -g "${dev_gid}" "${dev_group}"
                fi

                usermod -a -G "${dev_group}" "${APP_USER}"
                echo "[AFCD init] Device ${dev}: mode ${dev_mode}, group ${dev_gid} (${dev_group}) added to ${APP_USER}"
            else
                echo "[AFCD init] Device ${dev}: mode ${dev_mode}, root-owned group; no supplementary group added"
            fi
        fi
    done
fi

umask "${APP_UMASK}"

echo "[AFCD init] Final application identity:"
id "${APP_USER}"

exec gosu "${APP_USER}" "$@"
