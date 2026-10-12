SAN ANDREAS AUDIO TOOLBOX PC/PS2 GUI v1.8
========================================

A dual-platform GUI for Grand Theft Auto: San Andreas audio workflows.

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

The bundled original saat_stream.exe is Windows-only. The rest of the GUI and
PS2 tools are Python-based; PC SAAT operations require Windows.

PS2 WORKFLOW
------------
1. Select a PS2 station PAK and its matching AUDIO/CONFIG/TRAKLKUP.DAT.
2. Inspect archive and extract tracks.
3. Drop supported audio files onto the Track Browser or use the import control.
   For PS2 radio stream entries, audio is resampled and encoded at 32,000 Hz.
   The duplicated values in the legacy 8,068-byte header are not used as the
   PS2 ADPCM playback-rate setting.
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
- PS2 radio rate fix in v1.8: radio payloads are encoded at 32,000 Hz instead
  of inheriting 24,000/48,000 values from legacy stream-header metadata.
- Always make backups. Structurally valid output is not a guarantee of in-game
  playback; test in the relevant game/emulator.

SELF TEST
---------
python San_Andreas_Audio_Toolbox_PC_PS2_GUI.py --self-test
