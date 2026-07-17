# Toggle Wi-Fi on Wake
Simple macOS login hook script that waits a few seconds after wake/login, then toggles Wi-Fi off and back on to re-establish a stable connection.

## Script

- `toggle_wifi_on_wake.sh` – Main automation.

## Behavior

1. Sleeps for 4 seconds to allow Apple Watch unlock or other login processes to finish.
2. Determines the active Wi-Fi interface (`en0`/`en1`) via `networksetup -listallhardwareports`.
3. Turns Wi-Fi off, waits 2 seconds, and turns it back on.
4. Touches `ran_wifi_on_wake` in the script's directory as a marker that the script ran.

## Installation

1. Make the script executable: `chmod +x toggle_wifi_on_wake.sh`.
2. Register it as a LaunchAgent or use `sleepwatcher` / Hammerspoon to call it on wake:
   ```xml
   <!-- ~/Library/LaunchAgents/com.local.togglewifi.plist -->
   <plist version="1.0">
     <dict>
       <key>Label</key><string>com.local.togglewifi</string>
       <key>ProgramArguments</key>
         <array>
           <string>/path/to/toggle_wifi_on_wake.sh</string>
         </array>
       <key>RunAtLoad</key><true/>
     </dict>
   </plist>
   ```
3. Load the agent: `launchctl load ~/Library/LaunchAgents/com.local.togglewifi.plist`.

## Customization

- Adjust the initial `sleep` duration if unlock takes longer on your machine.
- Remove or relocate the marker file if you do not need a breadcrumb.
- Comment the `networksetup` lines and use `/usr/sbin/airport` if you prefer BSD-era tooling.
