#!/bin/sh
# E-paper panel for a Kindle: shows your pages from the e-Paper Panel add-on,
# and sleeps between updates.
#
# To the add-on this Kindle is a TRMNL: it speaks TRMNL's "bring your own
# server" protocol (addon/app/kinds/trmnl.py), over plain HTTP to the add-on's
# device port on the home network (a Kindle 4's TLS is too old for HTTPS).
#
#   pairing  GET /api/setup    ID (its Wi-Fi MAC), Model, FW-Version
#   a wake   GET /api/display  ID, Access-Token, battery, Wi-Fi, size, Update-Source
#            (timer, button, powercycle, and ours: back for the previous page,
#            refresh for the page on screen), ...
#            then the picture it names, drawn with the Kindle's own eips,
#            then sleep for refresh_rate seconds on the clock's alarm.
#
# Written for the Kindle 4's BusyBox 1.7 ash: POSIX sh, no arrays, and never
# BusyBox's `timeout` (it crashes there). Every call to the Kindle's hardware
# goes through a function below, so tests/test_kindle_client.py runs this same
# file on a computer with fake Kindle tools.
#
# Usage: epaper-panel.sh boot | run | stop | once

EPP_VERSION="1.0.0"                     # the client's own version, not the add-on's
EPP_HOME=${EPP_HOME:-/usr/local/epaper-panel}
EPP_STATE=${EPP_STATE:-/var/local/epaper-panel}
EPP_USERSTORE=${EPP_USERSTORE:-/mnt/us}
EPP_SETTINGS_NAME="epaper-panel.txt"
EPP_SYS=${EPP_SYS:-}                    # a test's stand-in for / (sysfs, /proc, /dev, the framework)
EPP_BOOT_SETTLE=${EPP_BOOT_SETTLE:-10}  # seconds after the Kindle has started before taking over
PATH=$PATH:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin    # eips is in /usr/sbin

# Waits after a failed wake, in seconds: 1, 2, 5, 10 and 30 minutes, then every
# 30 minutes (or the screen's own update interval when that's longer). Never a
# tight loop, and never more than one try per wait.
BACKOFF="60 120 300 600 1800"
SHORTEST=60                             # asleep, the add-on never asks for less (trmnl.shortest_sleep)
SHORTEST_AWAKE=5                        # always on, it asks as often as its pages turn
LONGEST=86400
DEFAULT_REFRESH=900
WIFI_WAIT=45                            # seconds for Wi-Fi to join before giving up this wake
# Measured on a Kindle 4 (client/kindle/README.md), as the CrowPanel's NEXT and PRV:
NEXT_KEYS=" 104 191 106 "               # next page (left, right side), 5-way right
BACK_KEYS=" 193 109 105 "               # previous page (left, right side), 5-way left
REFRESH_KEYS=" 194 "                    # 5-way middle: the page on screen, fetched and redrawn now
HOME_KEY=102                            # Home: the Kindle back, until the next restart
AWAKE_AFTER_PRESS=60                    # seconds it stays awake after a press, for the next one
BLANK="                                                  "   # a row of the Kindle's font: 50 columns

mkdir -p "$EPP_STATE" 2>/dev/null

# ------------------------------------------------------------------ small things

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$EPP_STATE/log"
}

trim_log() {
    [ -f "$EPP_STATE/log" ] || return 0
    if [ $(( $(wc -l < "$EPP_STATE/log") + 0 )) -gt 400 ]; then
        tail -n 200 "$EPP_STATE/log" > "$EPP_STATE/log.new" && mv "$EPP_STATE/log.new" "$EPP_STATE/log"
    fi
}

now_s() {
    date +%s
}

state_get() {
    [ -f "$EPP_STATE/$1" ] && cat "$EPP_STATE/$1"
}

state_put() {
    printf '%s' "$2" > "$EPP_STATE/$1.new" && mv "$EPP_STATE/$1.new" "$EPP_STATE/$1"
}

# "in 5 minutes", "in 1 hour": the Kindle's clock may be wrong, so never a time of day.
in_words() {
    s=$1
    if [ "$s" -lt 90 ]; then echo "in a minute"
    elif [ "$s" -lt 3300 ]; then echo "in $(( (s + 30) / 60 )) minutes"
    elif [ "$s" -lt 129600 ]; then
        h=$(( (s + 1800) / 3600 )); [ "$h" -eq 1 ] && echo "in an hour" || echo "in $h hours"
    else echo "tomorrow"
    fi
}

# A whole number of seconds the add-on asked for, kept within what makes sense.
clamp_refresh() {
    case "$1" in
        ''|*[!0-9]*) echo "$DEFAULT_REFRESH"; return ;;
    esac
    r=$1
    least=$SHORTEST
    [ "$(state_get stay)" = true ] && least=$SHORTEST_AWAKE
    [ "$r" -lt "$least" ] && r=$least
    [ "$r" -gt "$LONGEST" ] && r=$LONGEST
    echo "$r"
}

# The wait after the n-th failure in a row (1 is the first).
backoff_wait() {
    n=$1; i=1; w=60
    for step in $BACKOFF; do
        w=$step
        [ "$i" -ge "$n" ] && break
        i=$((i + 1))
    done
    longest=$(clamp_refresh "$(state_get refresh)")
    [ "$n" -gt 5 ] && [ "$longest" -gt "$w" ] && w=$longest
    echo "$w"
}

# One value from a flat JSON object (the add-on's answers are flat): a string's
# text, or a number or true/false as written. Nothing when it isn't there.
json_get() {
    awk -v k="$1" '
    { s = s $0 " " }
    END {
        n = length(s); i = 1; key = ""
        while (i <= n) {
            c = substr(s, i, 1)
            if (c == "\"") {
                j = i + 1; v = ""
                while (j <= n) {
                    d = substr(s, j, 1)
                    if (d == "\\") {
                        e = substr(s, j + 1, 1)
                        if (e == "u") { v = v "?"; j += 6; continue }
                        if (e == "n" || e == "t" || e == "r") e = " "
                        v = v e; j += 2; continue
                    }
                    if (d == "\"") break
                    v = v d; j++
                }
                i = j + 1
                while (substr(s, i, 1) ~ /[ \t]/) i++
                if (substr(s, i, 1) == ":") { key = v; i++; continue }
                if (key == k) { print v; exit }
                key = ""; continue
            }
            if (key != "" && c ~ /[-0-9tfn]/) {
                j = i
                while (j <= n && substr(s, j, 1) !~ /[,} \t]/) j++
                if (key == k) { print substr(s, i, j - i); exit }
                key = ""; i = j; continue
            }
            if (c == "{" || c == "[") key = ""
            i++
        }
    }' "$2"
}

# ------------------------------------------------------------------ settings

# The address of the add-on's device port, from epaper-panel.txt on the Kindle's
# drive ("server = http://192.168.1.20:8099"). Copied aside, so it's still known
# while the drive is plugged into a computer (and so away from the Kindle).
read_settings() {
    src="$EPP_USERSTORE/$EPP_SETTINGS_NAME"
    if [ -f "$src" ]; then
        tr -d '\r' < "$src" > "$EPP_STATE/settings.new" && mv "$EPP_STATE/settings.new" "$EPP_STATE/settings"
    fi
    SERVER=""
    [ -f "$EPP_STATE/settings" ] || return 1
    SERVER=$(sed -n 's/^[[:space:]]*server[[:space:]]*[=:][[:space:]]*//p' "$EPP_STATE/settings" | sed 's/[[:space:]]*$//; s#/*$##' | head -n 1)
    [ -n "$SERVER" ]
}

# Why an address can't be used, in plain words, or nothing when it can.
server_problem() {
    case "$1" in
        https://*) echo "This Kindle can't use https. In $EPP_SETTINGS_NAME, use the add-on's home address, starting with http://." ;;
        http://*) rest=${1#http://}
                  case "$rest" in
                      ''|*/*|*' '*) echo "The address in $EPP_SETTINGS_NAME isn't one this Kindle can use: $1" ;;
                  esac ;;
        *) echo "The address in $EPP_SETTINGS_NAME should start with http://, like http://192.168.1.20:8099" ;;
    esac
}

# ------------------------------------------------------------------ the Kindle

kindle_mac() {
    lipc-get-prop com.lab126.wifid macAddress 2>/dev/null | tr 'a-f' 'A-F'
}

# What it is, for the editor: "Kindle 4" from its serial number's device code.
kindle_model() {
    usid=$(cat "$EPP_SYS/proc/usid" 2>/dev/null)
    case "$usid" in
        B00E*|B023*|9023*) echo "Kindle 4" ;;
        *) echo "Kindle" ;;
    esac
}

kindle_firmware() {
    v=$(sed -n 's/^Kindle \([0-9.]*\).*/\1/p' "$EPP_SYS/etc/prettyversion.txt" 2>/dev/null)
    echo "$EPP_VERSION${v:+ / Kindle $v}"
}

# Its screen's size, as the framebuffer says: "600 800".
kindle_size() {
    sz=$(cat "$EPP_SYS/sys/class/graphics/fb0/virtual_size" 2>/dev/null)
    w=${sz%%,*}; h=${sz##*,}
    case "$w$h" in ''|*[!0-9]*) echo "600 800" ;; *) echo "$w $h" ;; esac
}

# Battery in volts ("3.92"), from the fuel gauge's millivolts.
kindle_battery_volts() {
    mv=$(gasgauge-info -v 2>/dev/null | sed 's/[^0-9]//g')
    case "$mv" in ''|*[!0-9]*) return 1 ;; esac
    printf '%d.%02d' $((mv / 1000)) $(((mv % 1000 + 5) / 10 % 100))
}

kindle_rssi() {
    iwconfig wlan0 2>/dev/null | sed -n 's/.*Signal level[=:]\(-[0-9]*\).*/\1/p' | head -n 1
}

# EPP_NETWORK=cable: the network is already there (testing over USBNetwork), so
# Wi-Fi is left alone. Not a setting: a Kindle is a Wi-Fi screen.
wifi_up() {
    [ "${EPP_NETWORK:-}" = cable ] && return 0
    lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
    i=0
    while [ "$i" -lt "$WIFI_WAIT" ]; do
        st=$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)
        [ "$st" = "CONNECTED" ] && return 0
        sleep 1; i=$((i + 1))
    done
    log "wifi: not connected after ${WIFI_WAIT}s (state: $st)"
    return 1
}

wifi_down() {
    [ "${EPP_NETWORK:-}" = cable ] && return 0
    lipc-set-prop com.lab126.cmd wirelessEnable 0 2>/dev/null
}

# Draw a picture over the whole screen, with a full refresh (no ghosting).
screen_picture() {
    eips -f -g "$1" >/dev/null 2>&1
}

screen_clear() {
    eips -c >/dev/null 2>&1
}

# One line of text at a row of the Kindle's own font (50 columns by 40 rows).
screen_text() {
    eips "$1" "$2" "$3" >/dev/null 2>&1
}

# Take the screen over: the Kindle's own reader is stopped so it doesn't draw
# over the pages or sleep on its own schedule. hand_back undoes it, Wi-Fi
# included: as the Kindle had it before (the client turns it off between wakes).
take_over() {
    w=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null)
    case "$w" in 0|1) state_put wireless_before "$w" ;; esac
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
    "$EPP_SYS/etc/init.d/framework" stop >/dev/null 2>&1
    sleep 2
}

# Home: the Kindle as it was, until it goes to sleep (the power switch, or
# dozing off on its own): then the pages come back instead of its screensaver.
hand_back() {
    log "handing the Kindle back, until it goes to sleep"
    stop_keys
    : > "$EPP_STATE/handed_back"
    lipc-set-prop com.lab126.cmd wirelessEnable "$(state_get wireless_before || echo 1)" 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
    "$EPP_SYS/etc/init.d/framework" start >/dev/null 2>&1
    back_when_asleep &
}

back_when_asleep() {
    # Blocks until powerd says the Kindle is going to its screensaver. Anything else
    # (an error, the client stopped): nothing; the next restart starts it as usual.
    lipc-wait-event com.lab126.powerd goingToScreenSaver >/dev/null 2>&1 || return 0
    [ -f "$EPP_STATE/handed_back" ] || return 0
    log "the Kindle went to sleep: the pages come back"
    exec "$EPP_HOME/epaper-panel.sh" run
}

# Sleep until `deadline` (seconds since 1970), suspended on the clock's alarm.
# Until `awake` (optional, seconds since 1970) it stays awake instead, so the
# page-turn buttons answer: they can't wake a sleeping Kindle 4; only its power
# switch can (measured). WAKE says why it returned: "timer" (the time is up),
# "button" (next page: a button, or the power switch), "back" (previous page),
# "refresh" (the page on screen, now), "home" (Home).
sleep_until() {
    deadline=$1; awake=${2:-0}; WAKE=timer
    while :; do
        now=$(now_s)
        left=$(( deadline - now ))
        key=$(take_key)
        if [ -n "$key" ]; then
            case "$BACK_KEYS" in *" $key "*) WAKE=back ;; *) WAKE=button ;; esac
            case "$REFRESH_KEYS" in *" $key "*) WAKE=refresh ;; esac
            [ "$key" = "$HOME_KEY" ] && WAKE=home
            return 0
        fi
        [ "$left" -le 0 ] && return 0
        if [ "$now" -ge "$awake" ] && [ "$left" -gt 20 ] && suspend_for $(( left - 5 )); then
            # Woken early with no key on record: the power switch. It means "show
            # me something now", like a TRMNL's button.
            if [ $(( deadline - $(now_s) )) -gt 15 ] && [ -z "$(peek_key)" ]; then
                WAKE=button; return 0
            fi
            continue
        fi
        sleep 1
    done
}

# Suspend to memory with the real-time clock set to wake it. Fails (returns 1)
# when it can't: on a computer's USB, say, where it stays awake, and the caller
# waits awake instead.
suspend_for() {
    secs=$1
    wake="$EPP_SYS/sys/devices/platform/mxc_rtc.0/wakeup_enable"
    [ -w "$wake" ] || return 1
    before=$(now_s)
    echo 0 > "$wake" 2>/dev/null
    echo "$secs" > "$wake" 2>/dev/null || return 1
    echo mem > "$EPP_SYS/sys/power/state" 2>/dev/null || return 1
    # Didn't go down at all (the kernel refused): wait awake.
    [ $(( $(now_s) - before )) -ge 2 ]
}

# ------------------------------------------------------------------ keys

# One reader per key device, each appending the code of every key pressed to
# $EPP_STATE/keys. take_key hands over the latest one, ignoring a key that
# repeats within a second (one page button bounces).
#
# The device stays open the whole time (fd 3): the keypad sends a press as a
# burst (a scan code, the key, a sync), and a reader that closed it after one
# event would miss the key (measured: only the 5-way, which sends the key
# first, got through).
start_keys() {
    stop_keys
    : > "$EPP_STATE/keys"
    for dev in "$EPP_SYS"/dev/input/event0 "$EPP_SYS"/dev/input/event1; do
        [ -r "$dev" ] || continue
        (
            exec 3< "$dev" || exit 0
            while :; do
                rec=$(dd bs=16 count=1 <&3 2>/dev/null | hexdump -v -e '8/2 "%u " "\n"')
                [ -n "$rec" ] || { sleep 1; continue; }
                # struct input_event: time (4 halves), type, code, value (2 halves)
                set -- $rec
                [ "$5" = 1 ] && [ "$7" = 1 ] && echo "$(now_s) $6" >> "$EPP_STATE/keys"
            done
        ) &
        echo $! >> "$EPP_STATE/keys.pids"
    done
}

stop_keys() {
    if [ -f "$EPP_STATE/keys.pids" ]; then
        for p in $(cat "$EPP_STATE/keys.pids"); do kill "$p" 2>/dev/null; done
        rm -f "$EPP_STATE/keys.pids"
    fi
}

peek_key() {
    [ -s "$EPP_STATE/keys" ] && tail -n 1 "$EPP_STATE/keys"
}

take_key() {
    last=$(peek_key)
    [ -n "$last" ] || return 0
    : > "$EPP_STATE/keys"
    at=${last%% *}; code=${last##* }
    before=$(state_get key_at)
    state_put key_at "$at"
    [ -n "$before" ] && [ $(( at - before )) -le 1 ] && return 0
    case "$NEXT_KEYS$BACK_KEYS$REFRESH_KEYS" in *" $code "*) echo "$code"; return 0 ;; esac
    [ "$code" = "$HOME_KEY" ] && echo "$code"
    return 0
}

# ------------------------------------------------------------------ what's on screen

# A note over the bottom of whatever is showing: the last page stays.
note() {
    log "note: $*"
    printf '%s\n' "$*" | awk '{
        n = split($0, w, " "); line = ""; out = 0
        for (i = 1; i <= n; i++) {
            if (length(line) + length(w[i]) + 1 > 48 && line != "") { print line; line = w[i]; out++ }
            else line = (line == "" ? w[i] : line " " w[i])
        }
        if (line != "") print line
    }' | tail -n 3 > "$EPP_STATE/note"
    rows=$(wc -l < "$EPP_STATE/note")
    row=$(( 39 - rows ))
    screen_text 0 "$row" "$BLANK"
    while IFS= read -r line; do
        row=$((row + 1))
        screen_text 0 "$row" "$(printf ' %s%s' "$line" "$BLANK" | cut -c1-50)"
    done < "$EPP_STATE/note"
}

# A whole screen of words, for when there's no page to keep (not set up, not paired).
card() {
    log "card: $*"
    screen_clear
    row=6
    printf '%s\n' "$@" | awk '{
        if ($0 == "") { print ""; next }
        n = split($0, w, " "); line = ""
        for (i = 1; i <= n; i++) {
            if (length(line) + length(w[i]) + 1 > 44 && line != "") { print line; line = w[i] }
            else line = (line == "" ? w[i] : line " " w[i])
        }
        if (line != "") print line
    }' > "$EPP_STATE/card"
    while IFS= read -r line; do
        screen_text 3 "$row" "$line"
        row=$((row + 1))
    done < "$EPP_STATE/card"
}

# The last picture again, without its note.
redraw() {
    [ -f "$EPP_STATE/note" ] || return 0
    rm -f "$EPP_STATE/note"
    [ -f "$EPP_STATE/last.png" ] && screen_picture "$EPP_STATE/last.png"
}

# Whether a file is a PNG of exactly the screen's size (what eips can draw).
png_fits() {
    sig=$(hexdump -n 8 -v -e '8/1 "%02x"' "$1" 2>/dev/null)
    [ "$sig" = "89504e470d0a1a0a" ] || return 1
    wh=$(hexdump -s 16 -n 8 -v -e '8/1 "%02x"' "$1" 2>/dev/null)
    [ ${#wh} -eq 16 ] || return 1
    set -- $(kindle_size)
    [ "$(( 0x$(echo "$wh" | cut -c1-8) ))" -eq "$1" ] && [ "$(( 0x$(echo "$wh" | cut -c9-16) ))" -eq "$2" ]
}

# ------------------------------------------------------------------ the protocol

# GET a URL into a file with headers ("Name: value" each). Prints the HTTP
# status, or 000 when nothing answered. The headers go to curl in a config
# file, so a value with spaces stays one value.
http_get() {
    url=$1; out=$2; shift 2
    rm -f "$out"
    : > "$EPP_STATE/curl.cfg"
    for h in "$@"; do
        esc=$(printf '%s' "$h" | sed 's/\\/\\\\/g; s/"/\\"/g')
        printf 'header = "%s"\n' "$esc" >> "$EPP_STATE/curl.cfg"
    done
    code=$(curl -s -m 40 --connect-timeout 10 -K "$EPP_STATE/curl.cfg" -o "$out" -w '%{http_code}' "$url" 2>/dev/null)
    case "$code" in ''|*[!0-9]*) code=000 ;; esac
    echo "$code"
}

# Pair inside the editor's ten-minute window. 0: paired (its key is kept).
pair() {
    mac=$(kindle_mac)
    code=$(http_get "$SERVER/api/setup" "$EPP_STATE/setup.json" \
        "ID: $mac" "Model: $(kindle_model)" "FW-Version: $(kindle_firmware)" "Content-Type: application/json")
    log "setup: HTTP $code"
    case "$code" in
        000) FAILED="Can't reach Home Assistant at $SERVER. Check the address in $EPP_SETTINGS_NAME and that the Kindle's Wi-Fi is your home network."; return 1 ;;
        200) ;;
        *) FAILED="Home Assistant answered with an error (HTTP $code)."; return 1 ;;
    esac
    status=$(json_get status "$EPP_STATE/setup.json")
    if [ "$status" = "200" ]; then
        key=$(json_get api_key "$EPP_STATE/setup.json")
        [ -n "$key" ] || { FAILED="Pairing didn't send a key. Pair it again in the editor."; return 1; }
        state_put key "$key"
        state_put friendly_id "$(json_get friendly_id "$EPP_STATE/setup.json")"
        state_put mac "$mac"
        rm -f "$EPP_STATE/last_name"
        PAIRED_SAYS=$(json_get message "$EPP_STATE/setup.json")
        log "paired as $(state_get friendly_id)"
        return 0
    fi
    NOT_PAIRED=$(json_get message "$EPP_STATE/setup.json")
    FAILED=${NOT_PAIRED:-Not paired yet. In Home Assistant, open e-Paper and add this Kindle as a device.}
    return 1
}

# One wake's request. Sets NEXT (seconds to sleep) and shows the page.
# 0: the page is on screen (new, or the same as before).
display() {
    key=$(state_get key)
    set -- $(kindle_size)
    w=$1; h=$2
    volts=$(kindle_battery_volts)
    rssi=$(kindle_rssi)
    cached=false
    [ -f "$EPP_STATE/last.png" ] && [ -n "$(state_get last_name)" ] && cached=true
    code=$(http_get "$SERVER/api/display" "$EPP_STATE/display.json" \
        "ID: $(state_get mac)" "Access-Token: $key" "Refresh-Rate: $(clamp_refresh "$(state_get refresh)")" \
        ${volts:+"Battery-Voltage: $volts"} ${rssi:+"RSSI: $rssi"} "Width: $w" "Height: $h" \
        "Model: $(kindle_model)" "FW-Version: $(kindle_firmware)" "Update-Source: $SOURCE" \
        "Image-Cached: $cached" "Wake-Time: $(state_get awake_ms)" "Content-Type: application/json")
    log "display ($SOURCE): HTTP $code"
    case "$code" in
        200) ;;
        000) FAILED="Can't reach Home Assistant at $SERVER."; return 1 ;;
        401|403)
            # Its key was replaced (paired again, or removed): back to pairing.
            rm -f "$EPP_STATE/key" "$EPP_STATE/last_name"
            FAILED="This Kindle isn't paired any more. Pair it again in the editor."; return 1 ;;
        429) FAILED="Home Assistant asked this Kindle to wait."; return 1 ;;
        *) FAILED="Home Assistant answered with an error (HTTP $code)."; return 1 ;;
    esac
    status=$(json_get status "$EPP_STATE/display.json")
    [ "${status:-0}" = "0" ] || { FAILED="Home Assistant answered with status $status."; return 1; }
    # Always on (Update every 1 minute in the editor): stay awake and connected. Ours, not TRMNL's.
    stay=$(json_get stay_awake "$EPP_STATE/display.json")
    [ "$stay" = true ] || stay=false
    [ "$stay" != "$(state_get stay)" ] && log "always on: $stay"
    state_put stay "$stay"
    refresh=$(clamp_refresh "$(json_get refresh_rate "$EPP_STATE/display.json")")
    state_put refresh "$refresh"
    NEXT=$refresh
    url=$(json_get image_url "$EPP_STATE/display.json")
    name=$(json_get filename "$EPP_STATE/display.json")
    # Nothing new: what's on screen stays (no download, no flash), unless a person asked
    # for it again (refresh): then it's redrawn whole, which also clears any ghosting.
    if [ -z "$url" ] || { [ -n "$name" ] && [ "$name" = "$(state_get last_name)" ] && [ -f "$EPP_STATE/last.png" ]; }; then
        if [ "$SOURCE" = refresh ] && [ -f "$EPP_STATE/last.png" ]; then
            rm -f "$EPP_STATE/note"; screen_picture "$EPP_STATE/last.png"
        else
            redraw
        fi
        return 0
    fi
    # Its key goes only to its own server (as a TRMNL's firmware does).
    case "$url" in
        "$SERVER"/*) ;;
        *) FAILED="The page's address isn't this Home Assistant's: $url"; return 1 ;;
    esac
    code=$(http_get "$url" "$EPP_STATE/next.png" "ID: $(state_get mac)" "Access-Token: $key")
    if [ "$code" != 200 ] || ! png_fits "$EPP_STATE/next.png"; then
        log "picture: HTTP $code, $(wc -c < "$EPP_STATE/next.png" 2>/dev/null || echo 0) bytes, not a ${w}x${h} PNG"
        rm -f "$EPP_STATE/next.png"
        FAILED="The new page didn't arrive whole."
        return 1
    fi
    mv "$EPP_STATE/next.png" "$EPP_STATE/last.png"
    state_put last_name "$name"
    rm -f "$EPP_STATE/note"
    screen_picture "$EPP_STATE/last.png"
    return 0
}

# One wake, start to end: Wi-Fi, pairing when it has no key, the page. Sets
# NEXT, the seconds until the next wake. Counts failures in a row for the back-off.
wake_once() {
    FAILED=""; NOT_PAIRED=""; PAIRED_SAYS=""; NEXT=""
    started=$(now_s)
    if ! read_settings; then
        card "E-paper panel" "" "This Kindle isn't set up yet." "" \
            "In the e-Paper editor in Home Assistant, choose Add new device, then Kindle, and follow its steps."
        NEXT=1800; return 1
    fi
    problem=$(server_problem "$SERVER")
    if [ -n "$problem" ]; then
        card "E-paper panel" "" "$problem"
        NEXT=1800; return 1
    fi
    ok=1
    if wifi_up; then
        if [ -n "$(state_get key)" ] || pair; then
            [ -n "$PAIRED_SAYS" ] && card "E-paper panel" "" "$PAIRED_SAYS"
            display && ok=0
        fi
    else
        FAILED="No Wi-Fi. Join your network in the Kindle's settings: press Home, then Menu, Settings, Wi-Fi Networks."
    fi
    [ "$(state_get stay)" = true ] || wifi_down
    if [ "$ok" -eq 0 ]; then
        state_put failures 0
    else
        n=$(( $(state_get failures || echo 0) + 1 ))
        state_put failures "$n"
        NEXT=$(backoff_wait "$n")
        again="Trying again $(in_words "$NEXT")."
        if [ -z "$(state_get key)" ]; then
            card "E-paper panel" "" "$FAILED" "" "$again"
        elif [ -f "$EPP_STATE/last.png" ]; then
            note "$FAILED $again"
        else
            card "E-paper panel" "" "$FAILED" "" "$again"
        fi
    fi
    state_put awake_ms $(( ($(now_s) - started) * 1000 ))
    trim_log
    return "$ok"
}

# ------------------------------------------------------------------ the loop

run() {
    log "starting ($EPP_VERSION)"
    rm -f "$EPP_STATE/handed_back"
    take_over
    start_keys
    SOURCE=powercycle
    while :; do
        wake_once
        until=$(( $(now_s) + ${NEXT:-$DEFAULT_REFRESH} ))
        awake=0
        case "$SOURCE" in button|back|refresh) awake=$(( $(now_s) + AWAKE_AFTER_PRESS )) ;; esac
        [ "$(state_get stay)" = true ] && awake=$until        # always on: never suspends
        sleep_until "$until" "$awake"
        case "$WAKE" in
            home) hand_back; return 0 ;;
            button) SOURCE=button ;;
            back) SOURCE=back ;;                   # ours: the add-on goes to the previous page
            refresh) SOURCE=refresh ;;             # ours: the page on screen, fetched now
            *) SOURCE=timer ;;
        esac
    done
}

# At boot (the init script): only once the Kindle has finished starting, and
# only when it's set up. A Kindle that isn't set up stays a Kindle.
boot() {
    i=0
    while [ ! -f "$EPP_USERSTORE/DONT_HALT_ON_REPAIR" ] && [ "$i" -lt 120 ]; do sleep 1; i=$((i + 1)); done
    sleep "$EPP_BOOT_SETTLE"
    if ! read_settings; then
        log "not set up: no address in $EPP_SETTINGS_NAME, so the Kindle stays a Kindle"
        return 0
    fi
    run
}

stop() {
    stop_keys
    if [ -f "$EPP_STATE/run.pid" ]; then kill "$(cat "$EPP_STATE/run.pid")" 2>/dev/null; rm -f "$EPP_STATE/run.pid"; fi
}

case "${1:-}" in
    boot) echo $$ > "$EPP_STATE/run.pid"; boot ;;
    run) echo $$ > "$EPP_STATE/run.pid"; run ;;
    once) SOURCE=${2:-timer}; wake_once ;;
    stop) stop ;;
    source) ;;                                   # tests: the functions only
    *) echo "usage: $0 boot|run|once|stop" >&2; exit 2 ;;
esac
