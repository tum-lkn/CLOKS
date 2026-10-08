#!/bin/sh
set -eu

influxdb3 serve --node-id=my-node-0 &
PID="$!"

echo "Waiting for InfluxDB to be ready..."
sleep 5

TOKEN_FILE="/admin.token"

echo "Creating admin token..."
OUT="$(influxdb3 create token --admin 2>&1 || true)"

# Extract first occurrence of apiv3_... (letters, digits, underscore, hyphen)
TOKEN="$(printf "%s" "$OUT" | grep -oE 'apiv3_[A-Za-z0-9_-]+' | head -n 1 || true)"

if [ -z "$TOKEN" ]; then
echo "ERROR: Could not extract token from output." >&2
echo "Raw output was:" >&2
printf "%s\n" "$OUT" >&2
kill "$PID" 2>/dev/null || true
exit 1
fi

# Save only the token (no ANSI, no extra text)
printf "%s" "$TOKEN" > "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"
echo "Saved token to $TOKEN_FILE"

wait "$PID"