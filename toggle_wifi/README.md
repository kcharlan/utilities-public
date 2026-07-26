# Toggle Wi-Fi on Wake

A small macOS shell script that resets the Wi-Fi connection by turning Wi-Fi
off and back on. The script performs one reset each time it is invoked; it does
not detect wake events itself.

## Requirements

- macOS
- The built-in `networksetup` command
- Write access to the script's directory, where it creates its marker file

## Behavior

1. Waits 4 seconds to allow login and unlock activity to settle.
2. Finds the Wi-Fi hardware interface with
   `networksetup -listallhardwareports`.
3. Turns Wi-Fi off, waits 2 seconds, and turns it back on.
4. Creates or updates `ran_wifi_on_wake` beside the script as a marker that the
   script ran.

The marker is a runtime file and is not part of the repository. If you run the
script from a repository checkout, it will appear as an untracked file.

## Run Manually

From this directory:

```sh
./toggle_wifi_on_wake.sh
```

If you copied the script elsewhere and its executable bit was not preserved,
run:

```sh
chmod +x /absolute/path/to/toggle_wifi_on_wake.sh
```

## Run at Login

A user LaunchAgent can run the script once when the agent is loaded, normally
at login. Replace the script path below with an absolute path; launchd does not
expand `~`.

1. Save this file as
   `~/Library/LaunchAgents/com.local.togglewifi.plist`:

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
     "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
     <dict>
       <key>Label</key>
       <string>com.local.togglewifi</string>
       <key>ProgramArguments</key>
       <array>
         <string>/absolute/path/to/toggle_wifi_on_wake.sh</string>
       </array>
       <key>RunAtLoad</key>
       <true/>
     </dict>
   </plist>
   ```

2. Register it for the current graphical login session:

   ```sh
   launchctl bootstrap "gui/$(id -u)" \
     "$HOME/Library/LaunchAgents/com.local.togglewifi.plist"
   ```

To unregister it:

```sh
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/com.local.togglewifi.plist"
```

## Run after Wake

`RunAtLoad` is a login/load trigger, not a wake trigger. To run the script
after every wake, configure a wake-aware utility such as SleepWatcher or
Hammerspoon to invoke the script's absolute path. Keep only one trigger active
if you do not want duplicate resets around login.

## Customize

- Change the initial `sleep 4` if the machine needs more or less time after
  login or wake.
- Remove or relocate the final `touch` command if you do not want the marker
  file beside the script.
