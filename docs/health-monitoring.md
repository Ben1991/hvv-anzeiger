# Lokaler Health-Check mit systemd

Der Check liest nur den Status des Anzeigedienstes. Er benötigt keinen
Webserver, keine Geofox-Zugangsdaten und keine neue Netzwerkverbindung.
Statuswerte sind unter „Gesundheit & Diagnose“ im Webinterface lesbar.

Beispiel `/etc/systemd/system/hvv-anzeiger-health.service`:

```ini
[Unit]
Description=Lokaler HVV-Gesundheitscheck
After=hvv-anzeiger.service

[Service]
Type=oneshot
User=hvv-anzeiger
Group=hvv-anzeiger
ExecStart=/opt/hvv-anzeiger/.venv/bin/python -m hvv_display.health --file /opt/hvv-anzeiger/var/health.json
TimeoutStartSec=5s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
```

Beispiel `/etc/systemd/system/hvv-anzeiger-health.timer`:

```ini
[Unit]
Description=HVV-Gesundheitscheck jede Minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
Unit=hvv-anzeiger-health.service

[Install]
WantedBy=timers.target
```

Nach dem Anlegen:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hvv-anzeiger-health.timer
journalctl -u hvv-anzeiger-health.service -n 20 --no-pager
```

Exit-Code 0 bedeutet gesund, 1 eingeschränkt/veraltet und 2 nicht
funktionsfähig. systemd markiert 1 und 2 als fehlgeschlagen; das Journal enthält
die redigierte JSON-Diagnose. Ein Monitoring-System kann dieselbe CLI verwenden.
Die Beispiele lösen keine Neustarts und keine Benachrichtigungen aus.
