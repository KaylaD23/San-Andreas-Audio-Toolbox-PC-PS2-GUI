SAN ANDREAS AUDIO TOOLBOX PC/PS2 GUI v3.0
========================================

A dual-platform GUI for Grand Theft Auto: San Andreas audio workflows.

THEME UPDATE (v3.0)
-------------------
- Removed the decorative “Los Santos” lettering from the right side of the header banner.
- Filled the cleared area with matching sunset skyline artwork and kept the PC + PS2 badge.

THEME UPDATE (v2.6)
-------------------
- Rebuilt the supplied SA emblem from the original source image at high quality, keeping its white background and strong outlines.
- Re-exported a multi-resolution Windows ICO with small-size renditions optimised for title bars and taskbars.
- Fixed Windows icon setup so Tk does not override the native ICO with a single large PNG, which was making the small icon appear muddy.
- Retained the responsive full-width banner and Pillow-free banner resize fallback from v2.4.

THEME UPDATE (v2.4)
-------------------
- Fixed banner scaling to use the actual full client width, including on maximized/DPI-scaled windows.
- Added a Pillow-free banner resize fallback so the artwork can still fill the window if Pillow has not yet been installed.

THEME UPDATE (v2.3)
-------------------
The interface uses a full-width, taller San Andreas-inspired sunset banner, olive-green
panels, warm gold borders, dark archive surfaces, a persistent audio status strip, and a simplified main workspace.
The “Advanced replacement tools & workspace” control expands the less-frequently
used audio replacement controls without crowding the main archive view.

TABS
----
- PS2 Track Browser: inspect/extract/rebuild PS2 radio .PAK files with the
  matching PS2 TRAKLKUP.DAT. Supports the separate PS2 audio replacement path.
- PC SAAT: wraps the original SAAT PC stream tool (saat_stream.exe) to export
  PC streams to OGG plus stream_import.ini, and import/rebuild a PC stream while
  updating a COPY of the PC TrakLkup.dat.
- Activity Log: displays tool output and errors.

PC SAAT WORKFLOW
----------------
1. Select a PC GTA SA stream file (for example, the BEATS stream) and an export
   directory in the PC SAAT tab.
2. Click EXPORT PC STREAM TO OGG. SAAT exports OGG files and stream_import.ini.
3. Edit/replace the exported stereo OGG tracks. Adjust stream_import.ini if
   needed to point at replacement filenames.
4. Choose a NEW target stream output path and a BACKUP COPY of PC
   audio/CONFIG/TrakLkup.dat.
5. Click IMPORT / REBUILD PC STREAM. The original SAAT tool creates the output
   stream and updates the selected lookup copy.

The PC SAAT tab expects the original Windows utility at saat/saat_stream.exe.
That executable was not present in the source ZIP supplied for this rebuild, so add
a legitimate copy at that path to enable PC stream export/import. The rest of the GUI
and PS2 tools are Python-based; PC SAAT operations require Windows.

PS2 WORKFLOW
------------
1. Select a PS2 station PAK and its matching AUDIO/CONFIG/TRAKLKUP.DAT.
2. Inspect archive and extract tracks.
3. Drop supported audio files onto the Track Browser or use the import control.
   The PS2 conversion creates both GTA SA stream representations: the 750 Hz
   mini stream plus the full stream at the target rate from the original header.
   It packs channels and chunk boundaries as expected by GTA SA PS2 (0x1000-byte
   mini section followed by 0x10000-byte left and right blocks per 0x21000 chunk).
4. Rebuild Archive + Verify. Use the generated PAK and lookup table together.
5. Test in PCSX2 before using the rebuilt image. Keep originals backed up.

REQUIREMENTS
------------
- Python 3.10+ with Tkinter.
- FFmpeg installed and available on PATH for audio conversion.
- NumPy + Numba and tkinterdnd2 for compiled PS2 encoding and native drag/drop.
  Run Setup_Dependencies.bat on Windows.
- PC SAAT functions use the included original Windows saat_stream.exe.

NOTES
-----
- PC SAAT uses OGG Vorbis for import; use stereo OGG files as described in the
  original SAAT manual. It updates the selected TrakLkup.dat during import.
- PC SAAT and PS2 PAK workflows are different formats. Do not use PC SAAT to
  import/rebuild PS2 PAKs, or the PS2 PAK tools to rebuild PC stream files.
- PS2 stream-format fix in v2.1: the prior versions wrote alternating left/right
  ADPCM frames and omitted the PS2 mini-stream/chunk layout. v2.1 writes a 750 Hz
  mini stream plus the 24,000 Hz full stream in 0x21000-byte chunks, with 0x10000
  bytes per channel for the full stream. Both independent channels' first ADPCM
  frames receive the stream-start flag. This is a structural fix; still verify
  playback in PCSX2.
- Always make backups. Structurally valid output is not a guarantee of in-game
  playback; test in the relevant game/emulator.

SELF TEST
---------
python San_Andreas_Audio_Toolbox_PC_PS2_GUI.py --self-test

Icon note (v2.8): the custom SA ICO is explicitly applied to the main Tk window. If Windows continues showing a cached old icon, close all instances and relaunch the app.
