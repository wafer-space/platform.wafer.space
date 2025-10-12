# Favicon Documentation

## Current Favicon (Blue)

The platform.wafer.space favicon is a **blue** version of the wafer.space favicon (rocket + wafer design).

This provides visual distinction in browser tabs between:
- wafer.space (black rocket)
- platform.wafer.space (blue rocket)

## Files

### Active Favicon Files
- `favicon.ico` - Multi-resolution ICO (16x16, 32x32, 48x48)
- `favicon-16x16.png` - 16x16 PNG
- `favicon-32x32.png` - 32x32 PNG
- `favicon-48x48.png` - 48x48 PNG
- `favicon-64x64.png` - 64x64 PNG
- `favicon-128x128.png` - 128x128 PNG
- `apple-touch-icon.png` - 180x180 Apple touch icon

## Color Variants for Future Use

Additional color variants are available in the repository for potential future use as status indicators:

### Red Variant
- Location: `final_favicons/status-red.ico` and `status-red-*.png`
- Potential use: Error states, critical alerts, deployment issues

### Green Variant
- Location: `final_favicons/status-green.ico` and `status-green-*.png`
- Potential use: Success states, healthy systems, completed deployments

## Regenerating Favicons

If you need to regenerate or create new color variants:

1. Download the original wafer.space favicon
2. Use ImageMagick to colorize the black elements:
   ```bash
   convert original.png -fuzz 20% \( +clone -fill "#COLOR" -opaque black \) \
       -compose over -composite output.png
   ```
3. Generate all required sizes
4. Create multi-resolution .ico file

## Related Issue

Created for: https://github.com/wafer-space/platform.wafer.space/issues/27
