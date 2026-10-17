#!/bin/bash
# macOS: vaatii Pythonin jossa on Tk 8.6+ (esim. brew install python-tk@3.14); järjestelmän Python 3.9 antaa tyhjän ikkunan
pip3 install pyinstaller && pyinstaller --windowed --onefile --name KuvaLajittelija kuvalajittelija.py
