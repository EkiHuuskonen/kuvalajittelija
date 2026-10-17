@echo off
rem Windows: rakentaa dist\KuvaLajittelija.exe
pip install pyinstaller
pyinstaller --windowed --onefile --name KuvaLajittelija kuvalajittelija.py
