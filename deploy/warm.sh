#!/usr/bin/env bash
# Build every bundled design once, from inside the machine, after a deploy.
#
# Two things force this shape.
#
# A cold build takes 20-200 s on a shared core, and Fly's proxy times out long
# requests: warming through the public URL returns 502 on the slowest designs
# even though the build completes server-side. Running inside the machine
# skips the proxy entirely.
#
# The cache lives in that machine's memory, so this must run after every
# deploy and after any restart. Whoever opens the link first should not be
# the one paying for the first build.
#
#   deploy/warm.sh [app-name]
set -euo pipefail

APP="${1:-ecarbon}"

echo "Warming ${APP} from inside the machine (bypasses the proxy timeout)"
flyctl ssh console --app "$APP" -C "python -c '
import base64, json, os, time, urllib.request

base = \"http://127.0.0.1:8080\"
# The service gates localhost exactly as it gates the internet; the machine
# holds the same credentials as a secret, so warm-up presents them properly
# rather than the service carving out an exemption it would have to defend.
user = os.environ.get(\"ECARBON_USER\", \"\")
password = os.environ.get(\"ECARBON_PASSWORD\", \"\")
headers = {}
if user and password:
    token = base64.b64encode((user + \":\" + password).encode()).decode()
    headers[\"Authorization\"] = \"Basic \" + token

def fetch(path, timeout=900):
    request = urllib.request.Request(base + path, headers=headers)
    return urllib.request.urlopen(request, timeout=timeout).read()

for project in json.loads(fetch(\"/projects\")):
    pid = project[\"id\"]
    started = time.time()
    try:
        fetch(\"/projects/\" + pid + \"/takeoff\")
        # The massing view re-reads the drawings for geometry the prebuilt
        # takeoff does not carry, so it is warmed too or the first viewer
        # waits 20 s for it.
        fetch(\"/projects/\" + pid + \"/massing\")
        # unspecified re-reads the assemblies schedule, so it is cold at
        # about 5 s until something asks for it.
        try:
            fetch(\"/projects/\" + pid + \"/unspecified\")
        except Exception:
            pass
        # Warm the traces too. A partition trace recomputes the partition
        # geometry -- about 16 s -- and it is the moment the demo is built
        # around, so the first press must not be the slow one.
        try:
            takeoff = json.loads(fetch(\"/projects/\" + pid + \"/takeoff\"))
            # Every line, not a prefix. The partition lines sit at the end
            # of the bill and are the only slow traces -- warming the first
            # twelve warmed everything except the ones that matter, and the
            # demo'\''s key press still took 97 s.
            for line in takeoff.get(\"lines\", []):
                try:
                    regions = json.loads(
                        fetch(\"/projects/\" + pid + \"/trace/\" + line[\"id\"])
                    )
                    # And the sheet image the interface will ask for, at the
                    # dpi it asks for. Rendering a 36x24 inch page is about
                    # two seconds, and the trace is the press the demo is
                    # built around.
                    for region in regions[:2]:
                        fetch(
                            \"/projects/\" + pid + \"/trace/\" + line[\"id\"]
                            + \"/image.png?page=\" + str(region[\"page\"])
                            + \"&dpi=120&highlight=0\"
                        )
                except Exception:
                    pass
        except Exception:
            pass
        print(\"  %-42s %6.1fs\" % (pid.split(\"_Technical\")[0], time.time() - started))
    except Exception as exc:
        print(\"  %-42s failed: %s\" % (pid.split(\"_Technical\")[0], exc))
'"
echo "Done. Subsequent requests are served from this machine's cache."
