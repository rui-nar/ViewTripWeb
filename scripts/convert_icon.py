#!/usr/bin/env python3
"""Generate a simple app icon for Strava registration."""

from PIL import Image, ImageDraw

def create_app_icon(size=(512, 512)):
    """Create the ViewTrip app icon."""
    # Create image with Strava orange background
    img = Image.new('RGBA', size, (252, 76, 2, 255))  # #FC4C02
    draw = ImageDraw.Draw(img)

    # Draw multiple track segments to represent merging
    # Track 1 (blue)
    track1_points = [(80, 180), (200, 150), (320, 180), (380, 220), (420, 260)]
    draw.line(track1_points, fill=(33, 150, 243, 255), width=8, joint='curve')  # Blue

    # Track 2 (green)
    track2_points = [(80, 320), (200, 350), (320, 320), (380, 280), (420, 240)]
    draw.line(track2_points, fill=(76, 175, 80, 255), width=8, joint='curve')  # Green

    # Merged track (white, connecting both)
    merged_points = [(380, 220), (400, 230), (420, 250)]
    draw.line(merged_points, fill=(255, 255, 255, 255), width=12, joint='curve')

    # Add start circles for each track
    draw.ellipse([60, 160, 100, 200], fill=(33, 150, 243, 255))  # Blue start
    draw.ellipse([60, 300, 100, 340], fill=(76, 175, 80, 255))   # Green start

    # Add end circle (merged)
    draw.ellipse([400, 230, 440, 270], fill=(255, 255, 255, 255))  # White end

    # Add arrows pointing to merge point
    # Blue arrow
    blue_arrow = [(350, 190), (370, 200), (350, 210)]
    draw.polygon(blue_arrow, fill=(33, 150, 243, 255))

    # Green arrow
    green_arrow = [(350, 310), (370, 300), (350, 290)]
    draw.polygon(green_arrow, fill=(76, 175, 80, 255))

    # Add merge symbol (two arrows converging)
    merge_arrow1 = [(390, 210), (410, 220), (390, 230)]
    merge_arrow2 = [(390, 250), (410, 240), (390, 260)]
    draw.polygon(merge_arrow1, fill=(255, 255, 255, 255))
    draw.polygon(merge_arrow2, fill=(255, 255, 255, 255))

    return img

if __name__ == "__main__":
    icon = create_app_icon()
    icon.save("app_icon.png", "PNG")
    print("App icon generated: app_icon.png")
    print("Size: 512x512 pixels")
    print("Upload this PNG file to your Strava app registration.")