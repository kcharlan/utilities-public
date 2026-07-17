#!/bin/bash

# Toggle Wi-Fi off and on to reset connection

#
# Add sleep to allow me to login with Apple Watch, then toggle wifi
#
sleep 4

# Get Wi-Fi interface name (usually en0 or en1)
wifi_interface=$(networksetup -listallhardwareports | \
                 awk '/Wi-Fi|AirPort/{getline; print $2}')

#echo $wifi_interface
# Turn Wi-Fi off
networksetup -setairportpower "$wifi_interface" off
sleep 2

# Turn Wi-Fi back on
networksetup -setairportpower "$wifi_interface" on

touch "$(dirname "$0")/ran_wifi_on_wake"

#sleep 10
#osascript -e 'tell application "Finder" to activate' -e 'tell application "System Events" to keystroke "k" using {command down}'

