# Putting it on the panel

## 1. Home Assistant

```bash
# from the SSH add-on
mkdir -p /config/epaper /config/www/epaper
# copy render.py, pages.py, sources.py, theme.py, fonts/ into /config/epaper/
python3 -c "import PIL; print('Pillow', PIL.__version__)"   # must succeed
```

Create `/config/epaper/secrets.json` from `secrets.example.json`. The token
comes from your HA profile page, bottom of the page, "Long-lived access
tokens".

Add the contents of `configuration-snippets.yaml` to `configuration.yaml`,
restart HA, then check it works:

```bash
python3 /config/epaper/render.py --batt 100
ls -la /config/www/epaper/frame.png
```

Open `http://<ha>:8123/local/epaper/frame.png` in a browser. That exact URL is
what the panel fetches, so if you can see it, so can the panel.

## 2. The panel

In `esphome/crowpanel-epaper.yaml`:
- fill in `secrets.yaml` with your wifi details
- replace `homeassistant.local` with Home Assistant's address (two URLs)
- **comment out the whole `deep_sleep:` block for the first flash**

Then, with the panel on USB:

```bash
esphome run crowpanel-epaper.yaml --device /dev/cu.wchusbserial210
```

Expect: the panel powers its display (GPIO7), joins wifi, posts the webhook,
pulls frame.png and draws it. The serial log tells you which step failed.

Once the picture is right, uncomment `deep_sleep:` and flash once more over
USB. From then on it is a battery device, and reflashing means catching it
awake -- which is what the stay-awake flag in stage 2 is for.

## Known unknowns

- **PSRAM variant.** The config assumes N8R8 (8 MB octal). If it will not boot,
  comment out the `psram:` block and read the real size from the boot log.
- **Battery pin.** The voltage divider's GPIO is not documented for this board.
  Until it is found, the footer battery figure is whatever the panel reports,
  which is currently nothing. Check the schematic.
- **Sleep current.** Measure it before mounting. The CH340 USB-serial chip on
  this board is the usual culprit for a disappointing figure.
