# tvh-radio
Turn almost any radio stream into a channel feed with song information video for Tvheadend. 

This project is under active initial development and therefor not available for public release just yet. Keep an eye out here, come back often and see the development progress.

### Development and testing methodology
End to end test:
`Pillow metadata -> GStreamer -> H.264 + AAC -> MPEG-TS -> UDP -> TVHeadend -> Plex LiveTV`

Basic acceptance criteria - Regression test checklist:
- video appears
- audio works
- metadata artwork updates
- no sustained GStreamer errors
- stream survives normal operation
- graceful shutdown works
- restart works
