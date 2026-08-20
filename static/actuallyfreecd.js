"use strict";

let drives = [];
let currentDrive = null;
let currentTracks = [];
let currentMetadata = null;

let currentDriveReadOffset = 0;

let currentRipJobId = null;
let ripPollTimer = null;
let metadataRequestGeneration = 0;

let currentArtworkToken = "";
let artworkEnabled = true;
let artworkLoadGeneration = 0;
let artworkLoading = false;

const metadataLocks = {
    albumArtist: false,
    year: false,
    album: false,
    genre: false,
    disc: false,
    artwork: false
};


const PREFERENCES_KEY =
    "actuallyfreecd.preferences.v1";


function loadPreferences() {

    try {

        const raw =
            window.localStorage.getItem(
                PREFERENCES_KEY
            );

        if (!raw) {

            return {};
        }

        const data =
            JSON.parse(
                raw
            );

        return (
            data
            && typeof data === "object"
        )
            ? data
            : {};

    }
    catch (error) {

        console.error(
            "Unable to load preferences:",
            error
        );

        return {};
    }
}


function savePreferences() {

    try {

        const data = {
            metadata_source:
                metadataButton?.value
                || "musicbrainz",

            output_format:
                outputFormat?.value
                || "FLAC",

            mp3_quality:
                mp3Quality?.value
                || "V0 (Highest VBR)",

            rip_mode:
                ripMode?.value
                || "Automatic",

            naming_preset:
                namingPreset?.value
                || (
                    "Artist\\Album (Year)"
                    + "\\## - Title"
                ),

            output_subfolder:
                selectedOutputSubfolder
                || "",

            eject_after_rip:
                Boolean(
                    ejectAfterRip?.checked
                )
        };

        window.localStorage.setItem(
            PREFERENCES_KEY,
            JSON.stringify(
                data
            )
        );

    }
    catch (error) {

        console.error(
            "Unable to save preferences:",
            error
        );
    }
}


function setSelectValueIfPresent(
    select,
    value
) {

    if (
        !select
        || value === undefined
        || value === null
    ) {

        return;
    }

    const exists =
        Array.from(
            select.options
        )
        .some(
            option =>
                option.value === value
        );

    if (exists) {

        select.value =
            value;
    }
}


function applySavedPreferences() {

    const preferences =
        loadPreferences();

    setSelectValueIfPresent(
        metadataButton,
        preferences.metadata_source
    );

    setSelectValueIfPresent(
        outputFormat,
        preferences.output_format
    );

    setSelectValueIfPresent(
        mp3Quality,
        preferences.mp3_quality
    );

    setSelectValueIfPresent(
        ripMode,
        preferences.rip_mode
    );

    setSelectValueIfPresent(
        namingPreset,
        preferences.naming_preset
    );

    selectedOutputSubfolder=preferences.output_subfolder || "";
    destination.value=selectedOutputSubfolder ? "/music/"+selectedOutputSubfolder : "/music";

    if (
        typeof preferences.eject_after_rip
        === "boolean"
    ) {

        ejectAfterRip.checked =
            preferences.eject_after_rip;
    }
}


/* ============================================================
   ELEMENTS
   ============================================================ */

const driveSelect =
    document.getElementById(
        "driveSelect"
    );

const discStatus =
    document.getElementById(
        "discStatus"
    );

const driveStatus =
    document.getElementById(
        "driveStatus"
    );

const driveModel =
    document.getElementById(
        "driveModel"
    );

const driveSettingsButton =
    document.getElementById(
        "driveSettingsButton"
    );

const releaseMatch =
    document.getElementById(
        "releaseMatch"
    );

const metadataSource =
    document.getElementById(
        "metadataSource"
    );

const albumArtist =
    document.getElementById(
        "albumArtist"
    );

const albumTitle =
    document.getElementById(
        "albumTitle"
    );

const year =
    document.getElementById(
        "year"
    );

const genre =
    document.getElementById(
        "genre"
    );

const releaseId =
    document.getElementById(
        "releaseId"
    );

const discNumber =
    document.getElementById(
        "discNumber"
    );

const discCount =
    document.getElementById(
        "discCount"
    );

const artworkImage =
    document.getElementById(
        "artworkImage"
    );

const artworkPlaceholder =
    document.getElementById(
        "artworkPlaceholder"
    );

const loadArtworkButton =
    document.getElementById(
        "loadArtworkButton"
    );

const removeArtworkButton =
    document.getElementById(
        "removeArtworkButton"
    );

const artworkFileInput =
    document.getElementById(
        "artworkFileInput"
    );

const artworkLockButton =
    document.querySelector(
        ".art-lock"
    );

const artistLockButton =
    document.querySelector(
        ".artist-lock"
    );

const yearLockButton =
    document.querySelector(
        ".year-lock"
    );

const albumLockButton =
    document.querySelector(
        ".album-lock"
    );

const genreLockButton =
    document.querySelector(
        ".genre-lock"
    );

const discLockButton =
    document.querySelector(
        ".disc-lock"
    );

const trackBody =
    document.getElementById(
        "trackBody"
    );

const metadataButton =
    document.getElementById(
        "metadataButton"
    );

const readDiscButton =
    document.getElementById(
        "readDiscButton"
    );

const ejectButton =
    document.getElementById(
        "ejectButton"
    );

const ejectAfterRip =
    document.getElementById(
        "ejectAfterRip"
    );

const aboutVersion =
    document.getElementById(
        "aboutVersion"
    );

const refreshButton =
    document.getElementById(
        "refreshButton"
    );

const selectAllButton =
    document.getElementById(
        "selectAllButton"
    );

const selectNoneButton =
    document.getElementById(
        "selectNoneButton"
    );

const destination =
    document.getElementById(
        "destination"
    );

const browseButton=document.getElementById("browseButton");
const folderBrowserModal=document.getElementById("folderBrowserModal");
const folderBrowserClose=document.getElementById("folderBrowserClose");
const folderBrowserCancel=document.getElementById("folderBrowserCancel");
const folderBrowserSelect=document.getElementById("folderBrowserSelect");
const folderBrowserUp=document.getElementById("folderBrowserUp");
const folderBrowserNew=document.getElementById("folderBrowserNew");
const folderBrowserPath=document.getElementById("folderBrowserPath");
const folderBrowserList=document.getElementById("folderBrowserList");
let selectedOutputSubfolder="";
let folderBrowserCurrentPath="";

const namingPreset =
    document.getElementById(
        "namingPreset"
    );

const outputFormat =
    document.getElementById(
        "outputFormat"
    );

const mp3Quality =
    document.getElementById(
        "mp3Quality"
    );

const ripMode =
    document.getElementById(
        "ripMode"
    );

const ripModeDescription =
    document.getElementById(
        "ripModeDescription"
    );

const ripButton =
    document.getElementById(
        "ripButton"
    );

const stopButton =
    document.getElementById(
        "stopButton"
    );

const ripStatus =
    document.getElementById(
        "ripStatus"
    );

const ripSummary =
    document.getElementById(
        "ripSummary"
    );

const progressBar =
    document.getElementById(
        "progressBar"
    );

const aboutButton =
    document.getElementById(
        "aboutButton"
    );

const aboutOverlay =
    document.getElementById(
        "aboutOverlay"
    );

const aboutCloseButton =
    document.getElementById(
        "aboutCloseButton"
    );

const ripCompleteOverlay =
    document.getElementById(
        "ripCompleteOverlay"
    );

const ripCompleteMessage =
    document.getElementById(
        "ripCompleteMessage"
    );

const ripCompleteCloseButton =
    document.getElementById(
        "ripCompleteCloseButton"
    );


/* ============================================================
   ARTWORK
   ============================================================ */

function clearArtwork(
    force = false
) {

    if (
        metadataLocks.artwork
        && !force
    ) {

        return;
    }

    artworkImage.removeAttribute(
        "src"
    );

    artworkImage.hidden =
        true;

    artworkPlaceholder.hidden =
        false;

    currentArtworkToken =
        "";

    artworkEnabled =
        false;

    removeArtworkButton.disabled =
        true;
}


async function showArtworkUrl(
    url,
    token = "",
    force = false
) {

    if (
        metadataLocks.artwork
        && !force
    ) {

        return false;
    }

    if (!url) {

        clearArtwork(
            force
        );

        return false;
    }

    const loadGeneration =
        ++artworkLoadGeneration;

    artworkLoading =
        true;

    const finalUrl =
        (
            url
            + (
                url.includes("?")
                    ? "&"
                    : "?"
            )
            + `afcd=${Date.now()}`
        );

    return await new Promise(
        resolve => {

            artworkImage.onload =
                () => {

                    if (
                        loadGeneration
                        !== artworkLoadGeneration
                    ) {

                        resolve(
                            false
                        );

                        return;
                    }

                    artworkPlaceholder.hidden =
                        true;

                    artworkImage.hidden =
                        false;

                    removeArtworkButton.disabled =
                        false;

                    currentArtworkToken =
                        token || "";

                    artworkEnabled =
                        true;

                    artworkLoading =
                        false;

                    resolve(
                        true
                    );
                };

            artworkImage.onerror =
                () => {

                    if (
                        loadGeneration
                        === artworkLoadGeneration
                    ) {

                        artworkLoading =
                            false;

                        clearArtwork(
                            force
                        );
                    }

                    resolve(
                        false
                    );
                };

            artworkImage.src =
                finalUrl;
        }
    );
}

async function loadArtwork(
    releaseMbid,
    force = false
) {

    if (
        metadataLocks.artwork
        && !force
    ) {

        return false;
    }

    if (!releaseMbid) {

        clearArtwork(
            force
        );

        return false;
    }

    const lookupGeneration =
        ++artworkLoadGeneration;

    artworkLoading =
        true;

    ripStatus.textContent =
        "Loading album artwork...";

    try {

        const response =
            await fetch(
                `/api/releases/${
                    encodeURIComponent(
                        releaseMbid
                    )
                }/artwork-cache`,
                {
                    method:
                        "POST",

                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

        if (
            lookupGeneration
            !== artworkLoadGeneration
        ) {

            return false;
        }

        if (!response.ok) {

            throw new Error(
                data.error
                || "No artwork found"
            );
        }

        return await showArtworkUrl(
            data.url,
            data.token,
            force
        );

    }
    catch (error) {

        if (
            lookupGeneration
            === artworkLoadGeneration
        ) {

            console.error(
                "Artwork lookup failed:",
                error
            );

            artworkLoading =
                false;

            clearArtwork(
                force
            );

            ripStatus.textContent =
                (
                    "Ready — album artwork "
                    + "is temporarily unavailable."
                );
        }

        return false;
    }
}

async function uploadManualArtwork(
    file
) {

    if (!file) {

        return;
    }

    const formData =
        new FormData();

    formData.append(
        "artwork",
        file
    );

    loadArtworkButton.disabled =
        true;

    ripStatus.textContent =
        "Loading artwork...";

    try {

        const response =
            await fetch(
                "/api/artwork/upload",
                {
                    method:
                        "POST",

                    body:
                        formData
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || "Unable to upload artwork"
            );
        }

        await showArtworkUrl(
            data.url,
            data.token,
            true
        );

        metadataLocks.artwork =
            true;

        updateLockButton(
            artworkLockButton,
            true
        );

        ripStatus.textContent =
            "Manual artwork loaded.";

    }
    catch (error) {

        if (
            requestGeneration
            !== metadataRequestGeneration
        ) {

            return;
        }

        console.error(
            error
        );

        ripStatus.textContent =
            (
                "Artwork error: "
                + error.message
            );
    }
    finally {

        loadArtworkButton.disabled =
            !currentDrive;

        artworkFileInput.value =
            "";
    }
}


function updateLockButton(
    button,
    locked
) {

    if (!button) {

        return;
    }

    button.textContent =
        locked
            ? "🔒︎"
            : "🔓︎";

    button.style.color =
        locked
            ? "#d62828"
            : "#159447";

    button.title =
        locked
            ? "Unlock this metadata field"
            : "Lock this metadata field";

    button.setAttribute(
        "aria-pressed",
        locked
            ? "true"
            : "false"
    );
}


function unlockAllMetadataFields() {

    metadataLocks.albumArtist = false;
    metadataLocks.year = false;
    metadataLocks.album = false;
    metadataLocks.genre = false;
    metadataLocks.disc = false;
    metadataLocks.artwork = false;

    updateLockButton(artistLockButton, false);
    updateLockButton(yearLockButton, false);
    updateLockButton(albumLockButton, false);
    updateLockButton(genreLockButton, false);
    updateLockButton(discLockButton, false);
    updateLockButton(artworkLockButton, false);
}


function toggleMetadataLock(
    key,
    button
) {

    metadataLocks[key] =
        !metadataLocks[key];

    updateLockButton(
        button,
        metadataLocks[key]
    );
}


/* ============================================================
   METADATA
   ============================================================ */

function clearMetadata() {

    if (!metadataLocks.albumArtist) {
        albumArtist.value = "";
    }

    if (!metadataLocks.album) {
        albumTitle.value = "";
    }

    if (!metadataLocks.year) {
        year.value = "";
    }

    if (!metadataLocks.genre) {
        genre.value = "";
    }

    releaseId.value =
        "";

    if (!metadataLocks.disc) {
        discNumber.value = "1";
        discCount.value = "1";
    }

    releaseMatch.innerHTML =
        "<option></option>";

    releaseMatch.disabled =
        true;

    metadataSource.textContent =
        "Source: None";

    currentTracks = [];
    currentMetadata = null;

    clearArtwork();

    renderTracks();
}


/* ============================================================
   GENERAL HELPERS
   ============================================================ */

function formatDriveName(
    drive
) {

    return [
        drive.vendor || "",
        drive.model || ""
    ]
    .filter(Boolean)
    .join(" ");
}


function formatOffset(
    value
) {

    const number =
        Number(value) || 0;

    if (number > 0) {

        return `+${number}`;
    }

    return String(
        number
    );
}


function durationText(
    track
) {

    return track.length || "";
}


function setProgress(
    value
) {

    let progress =
        Number(
            value || 0
        );

    progress = Math.max(
        0,
        Math.min(
            100,
            progress
        )
    );

    progressBar.style.width =
        `${progress}%`;

    progressBar.textContent =
        progress > 5
            ? `${Math.round(progress)}%`
            : "";
}


function setRipControlsRunning(
    running
) {

    ripButton.disabled =
        running
        || !currentDrive;

    stopButton.disabled =
        !running;

    driveSelect.disabled =
        running;

    refreshButton.disabled =
        running;

    readDiscButton.disabled =
        running;

    ejectButton.disabled =
        running
        || !currentDrive;

    driveSettingsButton.disabled =
        running
        || !currentDrive;

    metadataButton.disabled =
        running;

    releaseMatch.disabled =
        running
        || !currentMetadata
        || (
            currentMetadata
                .releases
                ?.length
            <= 1
        );

    selectAllButton.disabled =
        running;

    selectNoneButton.disabled =
        running;

    outputFormat.disabled =
        running;

    ripMode.disabled =
        running;

    if (running) {

        mp3Quality.disabled =
            true;

    }
    else {

        updateOutputControls();
    }
}


/* ============================================================
   DRIVE SETTINGS
   ============================================================ */

async function loadDriveSettings() {

    currentDriveReadOffset =
        0;

    if (!currentDrive) {

        driveSettingsButton.disabled =
            true;

        return;
    }

    driveSettingsButton.disabled =
        false;

    loadArtworkButton.disabled =
        false;

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/settings`,
                {
                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to read "
                    + "drive settings"
                )
            );
        }

        currentDriveReadOffset =
            Number(
                data.settings
                    ?.read_offset_samples
                ?? 0
            );

        const offsetSource =
            data.settings
                ?.offset_source
            || "default";

        driveSettingsButton.title =
            (
                "Read offset: "
                + formatOffset(
                    currentDriveReadOffset
                )
                + " samples"
                + (
                    offsetSource === "accuraterip"
                    ? " (AccurateRip)"
                    : (
                        offsetSource === "manual"
                        ? " (manual)"
                        : ""
                    )
                )
            );

        if (
            offsetSource === "accuraterip"
            && data.settings
                ?.offset_lookup
                ?.found
        ) {

            ripStatus.textContent =
                (
                    "Drive offset automatically "
                    + "found in AccurateRip: "
                    + formatOffset(
                        currentDriveReadOffset
                    )
                    + " samples"
                );
        }

    }
    catch (error) {

        console.error(
            error
        );

        currentDriveReadOffset =
            0;
    }
}


async function editDriveSettings() {

    if (
        !currentDrive
        || currentRipJobId
    ) {

        return;
    }

    const driveName =
        formatDriveName(
            currentDrive
        );

    const answer =
        window.prompt(
            (
                `Read offset for ${driveName}\n\n`
                + "Enter the drive read offset in samples.\n"
                + "Positive and negative values are allowed."
            ),
            String(
                currentDriveReadOffset
            )
        );

    if (answer === null) {

        return;
    }

    const trimmed =
        answer.trim();

    if (
        !/^[+-]?\d+$/.test(
            trimmed
        )
    ) {

        window.alert(
            "Please enter a whole number, for example 6, -6 or 0."
        );

        return;
    }

    const newOffset =
        Number(
            trimmed
        );

    if (
        newOffset < -5000
        || newOffset > 5000
    ) {

        window.alert(
            "The read offset must be between -5000 and +5000 samples."
        );

        return;
    }

    driveSettingsButton.disabled =
        true;

    loadArtworkButton.disabled =
        true;

    ripStatus.textContent =
        "Saving drive settings...";

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/settings`,
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            read_offset_samples:
                                newOffset
                        })
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to save "
                    + "drive settings"
                )
            );
        }

        currentDriveReadOffset =
            Number(
                data.settings
                    ?.read_offset_samples
                ?? newOffset
            );

        ripStatus.textContent =
            (
                "Drive read offset saved: "
                + `${formatOffset(
                    currentDriveReadOffset
                )} samples`
            );

    }
    catch (error) {

        console.error(
            error
        );

        ripStatus.textContent =
            (
                "Drive settings error: "
                + error.message
            );

    }
    finally {

        driveSettingsButton.disabled =
            !currentDrive;
    }
}


/* ============================================================
   TRACK TABLE
   ============================================================ */

function renderTracks() {

    trackBody.innerHTML =
        "";

    currentTracks.forEach(
        (track, index) => {

            const row =
                document.createElement(
                    "tr"
                );

            row.dataset.trackNumber =
                String(
                    track.number
                    ?? index + 1
                );

            row.innerHTML = `
                <td class="track-checkbox-cell">
                    <input
                        class="track-checkbox"
                        type="checkbox"
                        checked
                    >
                </td>

                <td>
                    ${track.number ?? index + 1}
                </td>

                <td>
                    <input
                        class="track-title"
                        type="text"
                    >
                </td>

                <td>
                    <input
                        class="track-artist"
                        type="text"
                    >
                </td>

                <td>
                    ${track.duration || ""}
                </td>

                <td class="track-status">
                    Ready
                </td>
            `;

            row.querySelector(
                ".track-title"
            ).value =
                track.title || "";

            row.querySelector(
                ".track-artist"
            ).value =
                track.artist || "";

            trackBody.appendChild(
                row
            );
        }
    );

    updateRipButtonState();
}


function buildTracks(
    physicalTracks,
    metadataTracks
) {

    return physicalTracks.map(
        (physical, index) => {

            const metadata =
                metadataTracks[index]
                || {};

            return {
                number:
                    physical.number
                    ?? index + 1,

                title:
                    metadata.title
                    || (
                        `Track ${
                            String(
                                index + 1
                            ).padStart(
                                2,
                                "0"
                            )
                        }`
                    ),

                artist:
                    metadata.artist
                    || "",

                duration:
                    durationText(
                        physical
                    )
            };
        }
    );
}


function updateTrackStatus(
    trackNumber,
    status
) {

    const row =
        trackBody.querySelector(
            `tr[data-track-number="${trackNumber}"]`
        );

    if (!row) {

        return;
    }

    const cell =
        row.querySelector(
            ".track-status"
        );

    if (cell) {

        cell.textContent =
            status || "";
    }
}


function resetTrackStatuses() {

    trackBody
        .querySelectorAll(
            ".track-status"
        )
        .forEach(
            cell => {

                cell.textContent =
                    "Ready";
            }
        );
}


function selectedTracksFromTable() {

    const selected =
        [];

    trackBody
        .querySelectorAll(
            "tr"
        )
        .forEach(
            row => {

                const checkbox =
                    row.querySelector(
                        ".track-checkbox"
                    );

                if (
                    !checkbox
                    || !checkbox.checked
                ) {

                    return;
                }

                const number =
                    Number(
                        row.dataset
                            .trackNumber
                    );

                const title =
                    row.querySelector(
                        ".track-title"
                    )
                    ?.value
                    .trim()
                    || (
                        `Track ${
                            String(
                                number
                            ).padStart(
                                2,
                                "0"
                            )
                        }`
                    );

                const artist =
                    row.querySelector(
                        ".track-artist"
                    )
                    ?.value
                    .trim()
                    || "";

                selected.push({
                    number,
                    title,
                    artist
                });
            }
        );

    return selected;
}


function selectedTrackCount() {

    return trackBody
        .querySelectorAll(
            ".track-checkbox:checked"
        )
        .length;
}


function updateRipButtonState() {

    if (currentRipJobId) {

        ripButton.disabled =
            true;

        return;
    }

    const disc =
        currentDrive?.disc
        || {};

    ripButton.disabled =
        !currentDrive
        || !disc.present
        || !disc.audio
        || artworkLoading
        || selectedTrackCount()
            === 0;
}



async function loadDestinationStatus() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

                if (
            aboutVersion
            && data.version
        ) {

            aboutVersion.textContent =
                data.version;
        }

if (!response.ok) {

            throw new Error(
                (
                    "Status request returned "
                    + response.status
                )
            );
        }

        const status =
            data.music_destination
            || {};

        destination.value =
            selectedOutputSubfolder
            ? "/music/" + selectedOutputSubfolder
            : (status.path || data.music_root || "/music");

        if (
            status.writable
        ) {

            browseButton.disabled =
                false;

            destination.title =
                (
                    "Music destination is "
                    + "mounted and writable."
                );

        }
        else {

            browseButton.disabled =
                true;

            destination.title =
                (
                    status.error
                    || (
                        "Music destination "
                        + "is not writable."
                    )
                );

            ripStatus.textContent =
                (
                    "Destination error: "
                    + destination.title
                );
        }

        return Boolean(
            status.writable
        );

    }
    catch (error) {

        console.error(
            error
        );

        browseButton.disabled =
            true;

        destination.value =
            "/music";

        destination.title =
            (
                "Unable to verify "
                + "music destination."
            );

        return false;
    }
}


async function loadFolderBrowser(path=""){const r=await fetch("/api/music-folders?path="+encodeURIComponent(path),{cache:"no-store"});const d=await r.json();if(!r.ok)throw new Error(d.error||"Unable to list folders");folderBrowserCurrentPath=d.path||"";folderBrowserPath.textContent=folderBrowserCurrentPath?"/music/"+folderBrowserCurrentPath:"/music";folderBrowserUp.disabled=!folderBrowserCurrentPath;folderBrowserList.innerHTML="";if(!d.folders.length){const e=document.createElement("div");e.className="folder-browser-empty";e.textContent="No subfolders";folderBrowserList.appendChild(e);return;}for(const f of d.folders){const b=document.createElement("button");b.type="button";b.className="folder-browser-item";b.textContent=f.name;b.addEventListener("click",async()=>await loadFolderBrowser(f.path));folderBrowserList.appendChild(b);}}
async function openFolderBrowser() {

    folderBrowserList.innerHTML =
        "";

    folderBrowserPath.textContent =
        "Refreshing...";

    folderBrowserModal.hidden =
        false;

    try {

        await loadFolderBrowser(
            selectedOutputSubfolder
        );

    }
    catch (error) {

        console.warn(
            "Saved destination no longer exists; "
            + "returning to /music.",
            error
        );

        selectedOutputSubfolder =
            "";

        destination.value =
            "/music";

        savePreferences();

        try {

            await loadFolderBrowser(
                ""
            );

        }
        catch (rootError) {

            alert(
                rootError.message
            );

            folderBrowserModal.hidden =
                true;
        }
    }
}
function closeFolderBrowser(){folderBrowserModal.hidden=true;}
async function createFolderFromBrowser(){const name=window.prompt("New folder name:");if(!name)return;const r=await fetch("/api/music-folders",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({parent:folderBrowserCurrentPath,name})});const d=await r.json();if(!r.ok){alert(d.error||"Unable to create folder");return;}await loadFolderBrowser(d.path);}


async function ejectCurrentDisc(
    quiet = false
) {

    if (
        !currentDrive
        || currentRipJobId
    ) {

        return false;
    }

    ejectButton.disabled =
        true;

    if (!quiet) {

        ripStatus.textContent =
            "Ejecting disc...";
    }

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/eject`,
                {
                    method:
                        "POST"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || "Unable to eject disc"
            );
        }

        if (!quiet) {

            ripStatus.textContent =
                "Disc ejected.";
        }

        window.setTimeout(
            loadDrives,
            700
        );

        return true;

    }
    catch (error) {

        console.error(
            error
        );

        if (!quiet) {

            ripStatus.textContent =
                (
                    "Eject error: "
                    + error.message
                );
        }

        return false;
    }
    finally {

        ejectButton.disabled =
            (
                !currentDrive
                || currentRipJobId
                !== null
            );
    }
}


/* ============================================================
   DRIVE DISCOVERY
   ============================================================ */

async function loadDrives() {

    if (currentRipJobId) {

        return;
    }

    await loadDestinationStatus();

    discStatus.textContent =
        "Checking server...";

    driveStatus.textContent =
        "Checking drive...";

    driveModel.textContent =
        "Unknown";

    ripStatus.textContent =
        "Looking for optical drives...";

    ripSummary.textContent =
        "";

    setProgress(
        0
    );

    clearMetadata();

    driveSettingsButton.disabled =
        true;

    try {

        const response =
            await fetch(
                "/api/drives",
                {
                    cache:
                        "no-store"
                }
            );

        if (!response.ok) {

            throw new Error(
                `Server returned ${
                    response.status
                }`
            );
        }

        const data =
            await response.json();

        drives =
            data.drives
            || [];

        driveSelect.innerHTML =
            "";

        if (!drives.length) {

            driveSelect.innerHTML =
                "<option></option>";

            currentDrive =
                null;

            currentDriveReadOffset =
                0;

            driveStatus.textContent =
                "No optical drives found";

            driveModel.textContent =
                "No drive";

            discStatus.textContent =
                "No optical drive detected.";

            ripStatus.textContent =
                "Ready.";

            updateRipButtonState();

            return;
        }

        drives.forEach(
            drive => {

                const option =
                    document.createElement(
                        "option"
                    );

                option.value =
                    drive.id;

                option.textContent =
                    formatDriveName(
                        drive
                    );

                driveSelect.appendChild(
                    option
                );
            }
        );

        await selectDrive(
            drives[0].id
        );

        await reconnectToActiveRip();

    }
    catch (error) {

        console.error(
            error
        );

        currentDrive =
            null;

        currentDriveReadOffset =
            0;

        discStatus.textContent =
            "Unable to contact server.";

        driveStatus.textContent =
            "No optical drives found";

        driveModel.textContent =
            "No drive";

        ripStatus.textContent =
            `Server error: ${
                error.message
            }`;

        updateRipButtonState();
    }

    ejectButton.disabled =
        (
            !currentDrive
            || currentRipJobId
            !== null
            || !(
                currentDrive.disc
                && currentDrive.disc.present
            )
        );

}


async function selectDrive(
    driveId
) {

    currentDrive =
        drives.find(
            item =>
                item.id
                === driveId
        );

    clearMetadata();

    setProgress(
        0
    );

    ripSummary.textContent =
        "";

    if (!currentDrive) {

        currentDriveReadOffset =
            0;

        driveSettingsButton.disabled =
            true;

        updateRipButtonState();

        return;
    }

    driveStatus.textContent =
        `Drive: ${
            currentDrive.device
        }`;

    driveModel.textContent =
        formatDriveName(
            currentDrive
        );

    await loadDriveSettings();

    const disc =
        currentDrive.disc
        || {};

    if (
        !disc.present
        || !disc.audio
    ) {

        discStatus.textContent =
            "No disc detected.";

        ripStatus.textContent =
            "Ready.";

        updateRipButtonState();

        return;
    }

    discStatus.textContent =
        (
            "Audio CD detected — "
            + `${disc.track_count} tracks.`
        );

    currentTracks =
        buildTracks(
            disc.tracks || [],
            []
        );

    renderTracks();

    ripStatus.textContent =
        "Ready.";

    const preferredMetadataSource =
        metadataButton.value
        || "musicbrainz";

    await loadMetadata(
        preferredMetadataSource
    );
}


/* ============================================================
   MUSICBRAINZ
   ============================================================ */

async function loadMetadata(source = "musicbrainz") {

    if (
        !currentDrive
        || currentRipJobId
    ) {

        return;
    }

    const disc =
        currentDrive.disc
        || {};

    if (
        !disc.present
        || !disc.audio
    ) {

        return;
    }

    const requestGeneration =
        ++metadataRequestGeneration;

    if (source === "manual") {

        currentMetadata =
            null;

        releaseMatch.innerHTML =
            "<option>Manual metadata</option>";

        releaseMatch.disabled =
            true;

        releaseId.value =
            "";

        metadataSource.textContent =
            "Source: Manual";

        discStatus.textContent =
            (
                "Audio CD detected — "
                + "manual metadata."
            );

        currentTracks =
            buildTracks(
                disc.tracks || [],
                []
            );

        renderTracks();

        ripStatus.textContent =
            "Enter or edit metadata manually.";

        updateRipButtonState();

        return;
    }

    metadataButton.disabled =
        true;

    const sourceName =
        source === "cdtext"
            ? "CD-Text"
            : "MusicBrainz";

    releaseMatch.innerHTML =
        (
            "<option>"
            + `Looking up ${sourceName}...`
            + "</option>"
        );

    releaseMatch.disabled =
        true;

    metadataSource.textContent =
        "Source: None";

    ripStatus.textContent =
        "Looking up metadata...";

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/metadata?source=${
                    encodeURIComponent(source)
                }`,
                {
                    cache:
                        "no-store"
                }
            );

        if (!response.ok) {

            throw new Error(
                (
                    "Metadata lookup returned "
                    + response.status
                )
            );
        }

        const data =
            await response.json();

        if (
            requestGeneration
            !== metadataRequestGeneration
        ) {

            return;
        }

        currentMetadata =
            data.metadata
            || {};

        if (
            currentMetadata.status
                !== "matched"
            || !currentMetadata
                .releases
                ?.length
        ) {

            releaseMatch.innerHTML =
                (
                    "<option>"
                    + (
                        source === "cdtext"
                            ? "No CD-Text found"
                            : "No MusicBrainz match"
                    )
                    + "</option>"
                );

            discStatus.textContent =
                (
                    "Audio CD detected — "
                    + (
                        source === "cdtext"
                            ? "no CD-Text found."
                            : "no matching release found."
                    )
                );

            ripStatus.textContent =
                "Ready.";

            updateRipButtonState();

            return;
        }

        releaseMatch.innerHTML =
            "";

        currentMetadata
            .releases
            .forEach(
                (
                    release,
                    index
                ) => {

                    const medium =
                        release
                            .matched_media
                            ?.[0];

                    const option =
                        document.createElement(
                            "option"
                        );

                    option.value =
                        String(
                            index
                        );

                    option.textContent =
                        (
                            `${release.artist || ""}`
                            + " — "
                            + `${release.title || ""}`
                            + (
                                medium
                                    ? ` · Disc ${medium.position}`
                                    : ""
                            )
                        );

                    releaseMatch.appendChild(
                        option
                    );
                }
            );

        releaseMatch.disabled =
            currentMetadata
                .releases
                .length
            <= 1;

        releaseMatch.value =
            "0";

        await applyRelease(
            0,
            source
        );

        if (source === "cdtext") {

            discStatus.textContent =
                "Audio CD detected — CD-Text loaded.";

        }
        else {

            discStatus.textContent =
                currentMetadata
                    .releases
                    .length
                === 1
                    ? (
                        "Audio CD detected — "
                        + "MusicBrainz found one "
                        + "matching release."
                    )
                    : (
                        "Audio CD detected — "
                        + `MusicBrainz found ${
                            currentMetadata
                                .releases
                                .length
                        } matching releases.`
                    );
        }

        ripStatus.textContent =
            "Ready.";

    }
    catch (error) {

        console.error(
            error
        );

        currentMetadata =
            null;

        releaseMatch.innerHTML =
            (
                "<option>"
                + "Metadata lookup failed"
                + "</option>"
            );

        releaseMatch.disabled =
            true;

        discStatus.textContent =
            (
                "Audio CD detected — "
                + "metadata lookup failed."
            );

        ripStatus.textContent =
            (
                "Metadata error: "
                + error.message
            );

    }
    finally {

        if (
            requestGeneration
            === metadataRequestGeneration
        ) {

            metadataButton.disabled =
                false;

            updateRipButtonState();
        }
    }
}


async function applyRelease(
    index,
    source = metadataButton.value || "musicbrainz"
) {

    if (!currentMetadata) {

        return;
    }

    const release =
        currentMetadata
            .releases
            ?.[index];

    if (!release) {

        return;
    }

    const medium =
        release
            .matched_media
            ?.[0];

    if (!metadataLocks.albumArtist) {

        albumArtist.value =
            release.artist || "";
    }

    if (!metadataLocks.album) {

        albumTitle.value =
            release.title || "";
    }

    if (!metadataLocks.year) {

        year.value =
            (
                release.date
                || ""
            ).substring(
                0,
                4
            );
    }

    if (!metadataLocks.genre) {

        genre.value =
            release.genre || "";
    }

    releaseId.value =
        release.release_mbid
        || "";

    if (!metadataLocks.disc) {

        discNumber.value =
            medium?.position
            ?? "1";

        discCount.value =
            release.medium_count
            ?? "1";
    }

    metadataSource.textContent =
        source === "cdtext"
            ? "Source: CD-Text"
            : "Source: MusicBrainz";

    currentTracks =
        buildTracks(
            currentDrive
                .disc
                ?.tracks
            || [],
            medium?.tracks
            || []
        );

    renderTracks();

    if (source === "musicbrainz") {

        await loadArtwork(
            release.release_mbid
        );

    }
    else {

        clearArtwork();
    }
}


/* ============================================================
   RIP PAYLOAD
   ============================================================ */

function buildRipMetadata() {

    return {
        album_artist:
            albumArtist
                .value
                .trim(),

        album:
            albumTitle
                .value
                .trim(),

        year:
            year
                .value
                .trim(),

        genre:
            genre
                .value
                .trim(),

        release_id:
            releaseId
                .value
                .trim(),

        disc_number:
            Number(
                discNumber.value
            )
            || 1,

        total_discs:
            Number(
                discCount.value
            )
            || 1,

        artwork_token:
            currentArtworkToken,

        artwork_enabled:
            artworkEnabled,

        output_subfolder:
            selectedOutputSubfolder
            || "",

        metadata_source:
            metadataButton.value
            || "manual"
    };
}


/* ============================================================
   START RIP
   ============================================================ */

async function startRip() {

    if (
        !currentDrive
        || currentRipJobId
    ) {

        return;
    }

    const destinationReady =
        await loadDestinationStatus();

    if (!destinationReady) {

        ripStatus.textContent =
            (
                "Cannot start rip — "
                + "music destination "
                + "is not writable."
            );

        return;
    }

    const tracks =
        selectedTracksFromTable();

    if (!tracks.length) {

        ripStatus.textContent =
            (
                "Select at least one "
                + "track to rip."
            );

        return;
    }

    resetTrackStatuses();

    tracks.forEach(
        track => {

            updateTrackStatus(
                track.number,
                "Queued"
            );
        }
    );

    setProgress(
        0
    );

    ripSummary.textContent =
        (
            "Preparing selected "
            + "tracks..."
        );

    ripStatus.textContent =
        (
            `Starting ${
                ripMode.value
            } rip...`
        );

    setRipControlsRunning(
        true
    );

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/rip`,
                {
                    method:
                        "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            tracks:
                                tracks,

                            metadata:
                                buildRipMetadata(),

                            rip_mode:
                                ripMode.value,

                            output_format:
                                outputFormat.value,

                            mp3_quality:
                                mp3Quality.value
,

                            naming_preset:
                                namingPreset.value,

                            eject_after_rip:
                                Boolean(
                                    ejectAfterRip.checked
                                )
                        })
                }
            );

        const data =
            await response.json();

        if (
            !response.ok
            && response.status === 409
            && data.job?.id
        ) {

            currentRipJobId =
                data.job.id;

            applyJobToInterface(
                data.job
            );

            setRipControlsRunning(
                true
            );

            startRipPolling();

            return;
        }

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to start "
                    + "rip job"
                )
            );
        }

        const job =
            data.job;

        if (!job?.id) {

            throw new Error(
                (
                    "Server did not return "
                    + "a rip job ID"
                )
            );
        }

        currentRipJobId =
            job.id;

        applyJobToInterface(
            job
        );

        startRipPolling();

    }
    catch (error) {

        console.error(
            error
        );

        currentRipJobId =
            null;

        ripStatus.textContent =
            (
                "Rip error: "
                + error.message
            );

        setRipControlsRunning(
            false
        );

        updateRipButtonState();
    }
}


async function reconnectToActiveRip() {

    if (!currentDrive) {

        return false;
    }

    try {

        const response =
            await fetch(
                `/api/drives/${
                    encodeURIComponent(
                        currentDrive.id
                    )
                }/active-rip`,
                {
                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to query "
                    + "active rip session"
                )
            );
        }

        if (
            !data.active
            || !data.job?.id
        ) {

            return false;
        }

        currentRipJobId =
            data.job.id;

        applyJobToInterface(
            data.job
        );

        setRipControlsRunning(
            true
        );

        startRipPolling();

        return true;

    }
    catch (error) {

        console.error(
            "Unable to reconnect to active rip:",
            error
        );

        return false;
    }
}


async function resynchroniseRipSession() {

    if (
        document.hidden
    ) {

        return;
    }

    if (
        currentRipJobId
    ) {

        await pollRipJob();
        return;
    }

    await reconnectToActiveRip();
}


/* ============================================================
   JOB POLLING
   ============================================================ */

function startRipPolling() {

    stopRipPolling();

    ripPollTimer =
        window.setInterval(
            pollRipJob,
            500
        );

    pollRipJob();
}


function stopRipPolling() {

    if (
        ripPollTimer
        !== null
    ) {

        window.clearInterval(
            ripPollTimer
        );

        ripPollTimer =
            null;
    }
}


async function pollRipJob() {

    if (!currentRipJobId) {

        return;
    }

    try {

        const response =
            await fetch(
                `/api/jobs/${
                    encodeURIComponent(
                        currentRipJobId
                    )
                }`,
                {
                    cache:
                        "no-store"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to read "
                    + "rip status"
                )
            );
        }

        const job =
            data.job;

        applyJobToInterface(
            job
        );

        if (
            job.status
                === "complete"
            || job.status
                === "failed"
            || job.status
                === "cancelled"
        ) {

            finishRipJob(
                job
            );
        }

    }
    catch (error) {

        console.error(
            error
        );

        stopRipPolling();

        ripStatus.textContent =
            (
                "Rip status error: "
                + error.message
            );

        stopButton.disabled =
            false;
    }
}


function applyJobToInterface(
    job
) {

    setProgress(
        job.progress
    );

    if (job.message) {

        ripStatus.textContent =
            job.message;
    }

    if (
        Array.isArray(
            job.tracks
        )
    ) {

        job.tracks.forEach(
            track => {

                updateTrackStatus(
                    track.number,
                    track.status
                );
            }
        );
    }

    if (
        job.total_tracks
        && job.status
            !== "complete"
    ) {

        ripSummary.textContent =
            (
                `${
                    job.completed_tracks
                    || 0
                }`
                + ` of ${
                    job.total_tracks
                }`
                + " selected tracks complete"
            );
    }
}


/* ============================================================
   FINISH RIP
   ============================================================ */

function finishRipJob(
    job
) {

    stopRipPolling();

    currentRipJobId =
        null;

    setRipControlsRunning(
        false
    );

    if (
        job.status
        === "complete"
    ) {

        setProgress(
            100
        );

        ripStatus.textContent =
            job.message
            || "Rip complete.";

        ripSummary.textContent =
            (
                "Completed successfully — "
                + `${job.completed_tracks}`
                + `/${job.total_tracks}`
                + " selected tracks"
            );

        ripCompleteMessage.textContent =
            (
                "Rip completed successfully — "
                + `${job.completed_tracks}`
                + `/${job.total_tracks}`
                + " selected tracks."
            );

        if (
            job.eject_after_rip
            && job.eject_status === "ejected"
        ) {

            ripCompleteMessage.textContent +=
                " Disc ejected.";
        }
        else if (
            job.eject_after_rip
            && job.eject_status === "failed"
        ) {

            ripCompleteMessage.textContent +=
                " Disc eject failed.";
        }

        ripCompleteOverlay.hidden =
            false;

    }
    else if (
        job.status
        === "cancelled"
    ) {

        ripStatus.textContent =
            job.message
            || "Rip cancelled.";

        ripSummary.textContent =
            (
                `${
                    job.completed_tracks
                    || 0
                }`
                + " tracks completed "
                + "before cancellation"
            );

    }
    else {

        ripStatus.textContent =
            job.error
                ? (
                    "Rip failed: "
                    + job.error
                )
                : "Rip failed.";

        ripSummary.textContent =
            (
                `${
                    job.completed_tracks
                    || 0
                }`
                + " tracks completed"
            );
    }

    updateRipButtonState();
}


/* ============================================================
   STOP RIP
   ============================================================ */

async function stopRip() {

    if (!currentRipJobId) {

        return;
    }

    stopButton.disabled =
        true;

    ripStatus.textContent =
        "Stopping rip safely...";

    try {

        const response =
            await fetch(
                `/api/jobs/${
                    encodeURIComponent(
                        currentRipJobId
                    )
                }/cancel`,
                {
                    method:
                        "POST"
                }
            );

        const data =
            await response.json();

        if (!response.ok) {

            throw new Error(
                data.error
                || (
                    "Unable to stop rip"
                )
            );
        }

        if (data.job) {

            applyJobToInterface(
                data.job
            );
        }

    }
    catch (error) {

        console.error(
            error
        );

        ripStatus.textContent =
            (
                "Stop error: "
                + error.message
            );

        stopButton.disabled =
            false;
    }
}


/* ============================================================
   OUTPUT CONTROLS
   ============================================================ */

function updateOutputControls() {

    mp3Quality.disabled =
        outputFormat.value
        === "FLAC"
        || currentRipJobId
        !== null;

    switch (
        outputFormat.value
    ) {

        case "MP3":

            ripButton.textContent =
                "Rip Selected to MP3";

            break;

        case "FLAC + MP3":

            ripButton.textContent =
                (
                    "Rip Selected to "
                    + "FLAC + MP3"
                );

            break;

        default:

            ripButton.textContent =
                "Rip Selected to FLAC";

            break;
    }

    updateRipButtonState();
}


function updateRipModeDescription() {

    switch (
        ripMode.value
    ) {

        case "Fast":

            ripModeDescription.textContent =
                (
                    "Single fast extraction pass. "
                    + "AccurateRip is checked when "
                    + "available, but a mismatch "
                    + "does not trigger rereading."
                );

            break;

        case "Secure":

            ripModeDescription.textContent =
                (
                    "Uses cdparanoia's full "
                    + "verification and correction "
                    + "mode from the start."
                );

            break;

        default:

            ripModeDescription.textContent =
                (
                    "Fast read first; if AccurateRip "
                    + "does not confirm it, retry once "
                    + "fast before secure fallback."
                );

            break;
    }
}


/* ============================================================
   EVENTS
   ============================================================ */

document.addEventListener(
    "visibilitychange",
    () => {

        if (
            !document.hidden
        ) {

            resynchroniseRipSession();
        }
    }
);


window.addEventListener(
    "focus",
    () => {

        resynchroniseRipSession();
    }
);


driveSelect.addEventListener(
    "change",
    async () => {

        await selectDrive(
            driveSelect.value
        );

        await reconnectToActiveRip();
    }
);


driveSettingsButton.addEventListener(
    "click",
    editDriveSettings
);

ejectButton.addEventListener(
    "click",
    () => {

        ejectCurrentDisc(
            false
        );
    }
);


ejectAfterRip.addEventListener(
    "change",
    savePreferences
);


loadArtworkButton.addEventListener(
    "click",
    () => {

        artworkFileInput.click();
    }
);


artworkFileInput.addEventListener(
    "change",
    () => {

        uploadManualArtwork(
            artworkFileInput.files?.[0]
        );
    }
);


removeArtworkButton.addEventListener(
    "click",
    () => {

        metadataLocks.artwork =
            false;

        updateLockButton(
            artworkLockButton,
            false
        );

        clearArtwork(
            true
        );

        ripStatus.textContent =
            "Artwork removed.";
    }
);


artworkLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "artwork",
            artworkLockButton
        );
    }
);


artistLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "albumArtist",
            artistLockButton
        );
    }
);


yearLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "year",
            yearLockButton
        );
    }
);


albumLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "album",
            albumLockButton
        );
    }
);


genreLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "genre",
            genreLockButton
        );
    }
);


discLockButton.addEventListener(
    "click",
    () => {

        toggleMetadataLock(
            "disc",
            discLockButton
        );
    }
);



releaseMatch.addEventListener(
    "change",
    async () => {

        await applyRelease(
            Number(
                releaseMatch.value
            ),
            metadataButton.value
        );
    }
);


refreshButton.addEventListener(
    "click",
    loadDrives
);


readDiscButton.addEventListener(
    "click",
    loadDrives
);


metadataButton.addEventListener(
    "change",
    async () => {

        const source =
            metadataButton.value;

        savePreferences();

        if (source === "musicbrainz") {

            unlockAllMetadataFields();

            clearMetadata();

            metadataButton.value =
                "musicbrainz";
        }

        await loadMetadata(
            source
        );
    }
);


selectAllButton.addEventListener(
    "click",
    () => {

        document
            .querySelectorAll(
                ".track-checkbox"
            )
            .forEach(
                item => {

                    item.checked =
                        true;
                }
            );

        updateRipButtonState();
    }
);


selectNoneButton.addEventListener(
    "click",
    () => {

        document
            .querySelectorAll(
                ".track-checkbox"
            )
            .forEach(
                item => {

                    item.checked =
                        false;
                }
            );

        updateRipButtonState();
    }
);


trackBody.addEventListener(
    "change",
    event => {

        if (
            event.target
                .classList
                .contains(
                    "track-checkbox"
                )
        ) {

            updateRipButtonState();
        }
    }
);


outputFormat.addEventListener(
    "change",
    () => {

        updateOutputControls();
        savePreferences();
    }
);


ripMode.addEventListener(
    "change",
    () => {

        updateRipModeDescription();
        savePreferences();
    }
);


mp3Quality.addEventListener(
    "change",
    savePreferences
);


namingPreset.addEventListener(
    "change",
    savePreferences
);


browseButton.addEventListener("click",openFolderBrowser);
folderBrowserClose.addEventListener("click",closeFolderBrowser);
folderBrowserCancel.addEventListener("click",closeFolderBrowser);
folderBrowserUp.addEventListener("click",async()=>{const p=folderBrowserCurrentPath.split("/").filter(Boolean);p.pop();await loadFolderBrowser(p.join("/"));});
folderBrowserNew.addEventListener("click",createFolderFromBrowser);
folderBrowserSelect.addEventListener("click",()=>{selectedOutputSubfolder=folderBrowserCurrentPath;destination.value=selectedOutputSubfolder?"/music/"+selectedOutputSubfolder:"/music";savePreferences();closeFolderBrowser();});

ripButton.addEventListener(
    "click",
    startRip
);


stopButton.addEventListener(
    "click",
    stopRip
);


ripCompleteCloseButton.addEventListener(
    "click",
    () => {

        ripCompleteOverlay.hidden =
            true;
    }
);


ripCompleteOverlay.addEventListener(
    "click",
    event => {

        if (
            event.target
            === ripCompleteOverlay
        ) {

            ripCompleteOverlay.hidden =
                true;
        }
    }
);


aboutButton.addEventListener(
    "click",
    () => {

        aboutOverlay.hidden =
            false;
    }
);


aboutCloseButton.addEventListener(
    "click",
    () => {

        aboutOverlay.hidden =
            true;
    }
);


aboutOverlay.addEventListener(
    "click",
    event => {

        if (
            event.target
            === aboutOverlay
        ) {

            aboutOverlay.hidden =
                true;
        }
    }
);


/* ============================================================
   START
   ============================================================ */

driveSettingsButton.disabled =
    true;

ejectButton.disabled =
    true;

browseButton.disabled =
    true;

[
    [artworkLockButton, false],
    [artistLockButton, false],
    [yearLockButton, false],
    [albumLockButton, false],
    [genreLockButton, false],
    [discLockButton, false]
].forEach(
    ([button, locked]) => {

        updateLockButton(
            button,
            locked
        );
    }
);

setProgress(
    0
);

applySavedPreferences();

updateOutputControls();

updateRipModeDescription();

loadDrives();