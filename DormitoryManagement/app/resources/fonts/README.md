# Bundled typefaces

## Interface: IBM Plex Sans Arabic

The application registers these unmodified upstream static fonts locally with Qt:

- `IBMPlexSansArabic-Regular.ttf`: body text, student data and input values (400).
- `IBMPlexSansArabic-Medium.ttf`: buttons and field labels (500).
- `IBMPlexSansArabic-SemiBold.ttf`: titles and table headings (600).

Source: <https://github.com/IBM/plex/tree/master/packages/plex-sans-arabic>.
The pinned upstream commit, exact download URLs and SHA256 hashes are recorded in
`ibm-plex-source.json`. Copyright and redistribution terms are in
`IBM-Plex-LICENSE.txt` (SIL Open Font License 1.1).

These files are loaded from the application resources without downloading or
installing fonts into Windows during normal use. Keep every face and the license
in the Windows distribution.

## Reports: Cairo

`Cairo.ttf` and its existing `OFL.txt` license remain dedicated to PDF and Excel
reports. Keeping the report typeface preserves existing Arabic text extraction,
search and print layout. PDF embeds the report font; Excel references its family
name and uses the spreadsheet application's font handling.
