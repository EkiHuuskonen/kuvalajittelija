# KuvaLajittelija

Kevyt kuvien/videoiden lajittelija. Yksi Python-tiedosto, vain vakiokirjasto (tkinter).

Ajo suoraan: `python3 kuvalajittelija.py`

Rakenne: `lajitellut/vuosi/kuukausi/{jpg,gif,movies,muut}`, `lajitellut/pienet_kuvat`,
`lajitellut/duplikaatit/vuosi/kuukausi/...`

- Päiväys: JPEG:n EXIF-kuvausaika, muuten tiedoston aikaleima (vanhin).
- Duplikaatti: täsmälleen sama sisältö (SHA-1). Valinnaisesti myös sama perusnimi + sama
  EXIF-aika eri koossa; suurin tiedosto jää päähakemistoon, muut duplikaatit-kansioon.
- Pienet kuvat: raja kt:ssa (videoihin ei sovelleta). Oletus kopioi, ei siirrä; "Esikatsele" ei muuta mitään.
- Rakennus: `rakenna.sh` (Mac) / `rakenna.bat` (Windows). Kumpikin pitää ajaa omalla alustallaan.
