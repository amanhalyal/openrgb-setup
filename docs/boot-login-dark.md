# Dark login screen after unattended startup

The Noctalia greeter configuration at
`/var/lib/noctalia-greeter/greeter.toml` sets `[idle].timeout = 60`.
Its compositor powers off outputs after one minute without input and wakes
them on keyboard or mouse input. The computer stays running for remote access.

`openrgb-boot-off.service` applies the existing Off profile before greetd
starts. It uses `openrgb-shutdown-off --boot`, including isolated controller
geometry, serialized SDK writes, and physical ENE verification. The temporary
server exits before the login screen starts, leaving the desktop's existing
OpenRGB autostart and wallpaper profile hook free to take ownership at login.
Boot mode refuses to run if another OpenRGB process already owns the hardware;
only the unchanged default shutdown mode may stop existing OpenRGB processes.

The boot service is enabled under multi-user.target. A greetd service drop-in
also Wants and orders it before greetd, so fast login cannot race the hardware
write. Failure or a 60-second timeout allows the login screen to start anyway.
The existing shutdown service keeps its own shutdown ordering.

Installation:

```sh
sudo install -m 0644 systemd/openrgb-boot-off.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/greetd.service.d
sudo tee /etc/systemd/system/greetd.service.d/openrgb-boot-off.conf <<'EOF'
[Unit]
Wants=openrgb-boot-off.service
After=openrgb-boot-off.service
EOF
sudo systemctl daemon-reload
sudo systemctl enable openrgb-boot-off.service
```

Do not restart greetd in an active desktop session to test this. The timeout
is read the next time the greeter starts. On the next cold boot, check that
RGB turns off, screens power off after 60 seconds, input wakes the login screen,
and login restores the wallpaper lighting. Inspect results with:

```sh
journalctl -b -u openrgb-boot-off.service
systemctl status openrgb-boot-off.service
```

Firmware lighting before Linux can access the devices may still appear.
