#!/bin/sh
# Display a static PNG from the gazette cache dir via eips
# (gazette.sh caches views as /mnt/us/documents/kindle-gazette/<name>.png)
# Usage: show_static.sh <image_name_without_extension>
IMG="/mnt/us/documents/kindle-gazette/${1}.png"
if [ -f "$IMG" ]; then
    eips -f -g "$IMG"
else
    eips -c
    eips 1 2 "Image not found: $IMG"
fi
