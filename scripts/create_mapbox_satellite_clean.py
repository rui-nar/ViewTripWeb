#!/usr/bin/env python3
"""
Creates a custom Mapbox style: satellite imagery + admin borders + place labels only.
No roads, buildings, POIs, or transit.

Requirements: Python 3.6+ (no third-party packages).

Usage:
    python create_mapbox_satellite_clean.py --token sk.xxx --username yourname

The token must have styles:write scope — use a secret token, not the
public token you pass to the Flutter app.

Get one at: mapbox.com → Account → Tokens → Create token → check styles:write
"""

import argparse
import json
import sys
import urllib.request
import urllib.error

# Layer IDs (or prefixes) to keep from satellite-streets-v12.
# Everything else (roads, buildings, POIs, transit, landuse) is dropped.
_KEEP_PREFIXES = (
    'admin-',           # country & state/province borders
    'country-label',    # country name labels
    'state-label',      # state / province name labels
    'settlement-label', # major city / town labels
    'continent-label',  # continent labels
)


def _get(url: str) -> dict:
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f'\nMapbox API error {e.code}: {body}', file=sys.stderr)
        sys.exit(1)


def _keep_layer(layer: dict) -> bool:
    if layer.get('type') == 'raster':
        return True  # satellite imagery background
    layer_id = layer.get('id', '')
    return any(layer_id.startswith(p) for p in _KEEP_PREFIXES)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--token', required=True,
                        help='Mapbox secret token with styles:write scope (sk.ey...)')
    parser.add_argument('--username', required=True,
                        help='Mapbox account username')
    parser.add_argument('--name', default='Satellite Clean',
                        help='Name for the new style (default: "Satellite Clean")')
    args = parser.parse_args()

    print('Fetching satellite-streets-v12 …')
    style = _get(
        f'https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12'
        f'?access_token={args.token}'
    )

    before = len(style.get('layers', []))
    style['layers'] = [l for l in style.get('layers', []) if _keep_layer(l)]
    after = len(style['layers'])
    print(f'Layers: {before} → {after} kept')

    # Remove read-only fields Mapbox rejects on POST (version is required, keep it)
    for field in ('id', 'owner', 'created', 'modified', 'draft'):
        style.pop(field, None)
    style['name'] = args.name

    print(f'Creating style "{args.name}" for user {args.username} …')
    result = _post(
        f'https://api.mapbox.com/styles/v1/{args.username}'
        f'?access_token={args.token}',
        style,
    )

    style_id = result['id']
    owner = result.get('owner', args.username)
    uri = f'mapbox://styles/{owner}/{style_id}?access_token={{key}}'

    print(f'\nDone!  Style URI:\n  {uri}')
    print(f'\nReplace kMapboxViewStyleUri in basemaps.dart with:')
    print(f"  const kMapboxViewStyleUri = '{uri}';")


if __name__ == '__main__':
    main()
