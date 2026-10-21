# Icons shipped with the add-on

`mdi.json.gz`: [Material Design Icons](https://pictogrammers.com/library/mdi/)
7.4.47 by Pictogrammers, Apache License 2.0, as Home Assistant's frontend
serves them (`/static/mdi/`): `{"prefix", "version", "icons": {name: path}}`,
each path on the 24 x 24 grid. To update it to the version Home Assistant
uses, run `iconsets.copy_home_assistant` against a Home Assistant and copy
`/data/icons/mdi.json.gz` here with `"from": "shipped"`.
