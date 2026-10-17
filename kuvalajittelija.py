#!/usr/bin/env python3
"""KuvaLajittelija – kevyt kuvien ja videoiden lajittelija (Windows + macOS).

Käy kansion läpi, löytää kuvat ja videot, tunnistaa duplikaatit ja lajittelee:
  lajitellut/vuosi/kuukausi/jpg | gif | movies | muut
  lajitellut/pienet_kuvat
  lajitellut/duplikaatit/vuosi/kuukausi/...

Vain Pythonin vakiokirjasto (tkinter). Ei ulkoisia riippuvuuksia.
"""
import hashlib
import os
import queue
import re
import shutil
import struct
import threading
from datetime import datetime

KANSIO = "lajitellut"
JPG = {".jpg", ".jpeg"}
GIF = {".gif"}
VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv", ".mpg", ".mpeg", ".3gp", ".webm", ".mts", ".m2ts"}
MUUT = {".png", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".webp"}


def tyyppi(ext):
    if ext in JPG:
        return "jpg"
    if ext in GIF:
        return "gif"
    if ext in VIDEO:
        return "movies"
    if ext in MUUT:
        return "muut"
    return None


# ---------------------------------------------------------------- EXIF
def exif_aika(polku):
    """Palauttaa JPEG:n EXIF-kuvausajan (datetime) tai None."""
    try:
        with open(polku, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None
            while True:
                m = f.read(2)
                if len(m) < 2 or m[0] != 0xFF:
                    return None
                if m[1] == 0xDA:  # kuvadata alkaa
                    return None
                ln = struct.unpack(">H", f.read(2))[0]
                data = f.read(ln - 2)
                if m[1] == 0xE1 and data[:6] == b"Exif\x00\x00":
                    return _tiff_aika(data[6:])
    except Exception:
        return None


def _tiff_aika(t):
    if t[:2] == b"II":
        e = "<"
    elif t[:2] == b"MM":
        e = ">"
    else:
        return None

    def u16(o):
        return struct.unpack(e + "H", t[o:o + 2])[0]

    def u32(o):
        return struct.unpack(e + "I", t[o:o + 4])[0]

    def ifd(o):
        r = {}
        for i in range(u16(o)):
            p = o + 2 + i * 12
            tag, typ, cnt = u16(p), u16(p + 2), u32(p + 4)
            if typ == 2:  # ASCII
                off = u32(p + 8) if cnt > 4 else p + 8
                r[tag] = t[off:off + cnt].rstrip(b"\x00").decode("ascii", "ignore")
            elif typ == 4:
                r[tag] = u32(p + 8)
        return r

    try:
        i0 = ifd(u32(4))
        s = None
        if 0x8769 in i0:
            s = ifd(i0[0x8769]).get(0x9003)
        s = s or i0.get(0x0132)
        if s:
            return datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def tiedoston_aika(polku, ext):
    if ext in JPG:
        d = exif_aika(polku)
        if d and d.year > 1970:
            return d, True
    st = os.stat(polku)
    ts = [st.st_mtime]
    if hasattr(st, "st_birthtime"):
        ts.append(st.st_birthtime)
    elif os.name == "nt":
        ts.append(st.st_ctime)
    return datetime.fromtimestamp(min(ts)), False


# ---------------------------------------------------------------- logiikka
def kerää(lahde, kohde, loki):
    tulos = []
    kohde_n = os.path.normcase(os.path.abspath(kohde))
    for juuri, kansiot, tiedostot in os.walk(lahde):
        kansiot[:] = [k for k in kansiot if not k.startswith(".")
                      and os.path.normcase(os.path.abspath(os.path.join(juuri, k))) != kohde_n]
        for n in tiedostot:
            if n.startswith("."):
                continue
            ext = os.path.splitext(n)[1].lower()
            t = tyyppi(ext)
            if t:
                p = os.path.join(juuri, n)
                try:
                    tulos.append((p, ext, t, os.path.getsize(p)))
                except OSError:
                    pass
    return tulos


def sha1(polku):
    h = hashlib.sha1()
    with open(polku, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


_STEM = re.compile(r"(\s*\(\d+\)|[-_ ]?(copy|kopio)(\s*\d+)?|[-_]\d)$", re.I)


def perusnimi(polku):
    s = os.path.splitext(os.path.basename(polku))[0].lower()
    while True:
        u = _STEM.sub("", s)
        if u == s:
            return s
        s = u


def suunnittele(lahde, kohde, pieni_kb, samannimiset, loki, edistyy=lambda a, b: None):
    """Palauttaa listan (lähde, kohdekansio-suhteellinen, luokka) ja tilastot."""
    tiedostot = kerää(lahde, kohde, loki)
    loki("Löytyi %d kuvaa/videota." % len(tiedostot))

    # 1) täsmälleen samat tiedostot (koko + SHA-1)
    kokoryhmät = {}
    for t in tiedostot:
        kokoryhmät.setdefault(t[3], []).append(t)
    ryhmät = []
    yksin = []
    kaikki = len(tiedostot)
    tehty = 0
    for koko, lst in kokoryhmät.items():
        if len(lst) == 1:
            yksin.append(lst[0])
        else:
            h = {}
            for t in lst:
                try:
                    h.setdefault(sha1(t[0]), []).append(t)
                except OSError:
                    yksin.append(t)
            for g in h.values():
                (ryhmät if len(g) > 1 else yksin).extend([g] if len(g) > 1 else g)
        tehty += len(lst)
        edistyy(tehty, kaikki)

    voittajat, duplikaatit = [], []

    def valitse(g):
        # suurin tiedosto voittaa; tasatilanteessa lyhin polku (yleensä alkuperäinen)
        g = sorted(g, key=lambda t: (-t[3], len(t[0]), t[0]))
        return g[0], g[1:]

    for g in ryhmät:
        v, d = valitse(g)
        voittajat.append(v)
        duplikaatit += [(x, v) for x in d]
    voittajat += yksin

    # 2) valinnainen: sama perusnimi + sama kuvausaika, eri koko -> suurin voittaa
    if samannimiset:
        ryhmä = {}
        loput = []
        for t in voittajat:
            if t[1] in JPG:
                d = exif_aika(t[0])
                if d:
                    ryhmä.setdefault((perusnimi(t[0]), t[2], d), []).append(t)
                    continue
            loput.append(t)
        voittajat = loput
        for g in ryhmä.values():
            v, d = valitse(g)
            voittajat.append(v)
            duplikaatit += [(x, v) for x in d]

    suunnitelma = []
    pieniä = 0

    def sijoita(t, etuliite, malli=None):
        d, _ = tiedoston_aika(*(malli or t)[:2])
        return os.path.join(etuliite, "%04d" % d.year, "%02d" % d.month, t[2])

    for t, v in duplikaatit:  # päiväys alkuperäisen (voittajan) mukaan
        suunnitelma.append((t[0], sijoita(t, "duplikaatit", v), "duplikaatti"))
    for t in voittajat:
        if t[2] != "movies" and pieni_kb > 0 and t[3] < pieni_kb * 1024:
            suunnitelma.append((t[0], "pienet_kuvat", "pieni"))
            pieniä += 1
        else:
            suunnitelma.append((t[0], sijoita(t, ""), "normaali"))
    tilasto = {"yhteensä": len(tiedostot), "duplikaatit": len(duplikaatit), "pienet": pieniä}
    return suunnitelma, tilasto


def vapaa_nimi(polku):
    if not os.path.exists(polku):
        return polku
    base, ext = os.path.splitext(polku)
    i = 1
    while os.path.exists("%s_%d%s" % (base, i, ext)):
        i += 1
    return "%s_%d%s" % (base, i, ext)


def suorita(suunnitelma, kohde, siirra, loki, edistyy=lambda a, b: None):
    virheet = 0
    for i, (src, rel, _) in enumerate(suunnitelma, 1):
        try:
            dst_dir = os.path.join(kohde, rel)
            os.makedirs(dst_dir, exist_ok=True)
            dst = vapaa_nimi(os.path.join(dst_dir, os.path.basename(src)))
            (shutil.move if siirra else shutil.copy2)(src, dst)
        except Exception as e:
            virheet += 1
            loki("VIRHE %s: %s" % (src, e))
        if i % 20 == 0 or i == len(suunnitelma):
            edistyy(i, len(suunnitelma))
    return virheet


# ---------------------------------------------------------------- käyttöliittymä
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("KuvaLajittelija")
    root.geometry("640x520")
    root.minsize(560, 460)

    lahde = tk.StringVar()
    kohde = tk.StringVar()
    pieni = tk.StringVar(value="100")
    samann = tk.BooleanVar(value=False)
    siirra = tk.BooleanVar(value=False)
    jono = queue.Queue()
    ty = {"käy": False}

    def valitse_lahde():
        p = filedialog.askdirectory(title="Valitse kansio, jonka kuvat lajitellaan")
        if p:
            lahde.set(p)
            if not kohde.get():
                kohde.set(os.path.join(p, KANSIO))

    def valitse_kohde():
        p = filedialog.askdirectory(title="Valitse kohdekansio")
        if p:
            kohde.set(p)

    f = ttk.Frame(root, padding=12)
    f.pack(fill="both", expand=True)
    f.columnconfigure(1, weight=1)

    ttk.Label(f, text="Lähdekansio:").grid(row=0, column=0, sticky="w", pady=3)
    ttk.Entry(f, textvariable=lahde).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Button(f, text="Valitse…", command=valitse_lahde).grid(row=0, column=2)
    ttk.Label(f, text="Kohdekansio:").grid(row=1, column=0, sticky="w", pady=3)
    ttk.Entry(f, textvariable=kohde).grid(row=1, column=1, sticky="ew", padx=6)
    ttk.Button(f, text="Valitse…", command=valitse_kohde).grid(row=1, column=2)

    o = ttk.Frame(f)
    o.grid(row=2, column=0, columnspan=3, sticky="w", pady=8)
    ttk.Label(o, text="Pienet kuvat: alle").grid(row=0, column=0, sticky="w")
    ttk.Entry(o, textvariable=pieni, width=6).grid(row=0, column=1, padx=4)
    ttk.Label(o, text="kt (0 = ei erottelua)").grid(row=0, column=2, sticky="w")
    ttk.Checkbutton(o, variable=samann,
                    text="Tunnista duplikaatiksi myös saman nimiset + saman kuvausajan kuvat (eri koko)"
                    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=2)
    ttk.Radiobutton(o, variable=siirra, value=False, text="Kopioi (turvallinen, alkuperäiset säilyvät)"
                    ).grid(row=2, column=0, columnspan=3, sticky="w")
    ttk.Radiobutton(o, variable=siirra, value=True, text="Siirrä (alkuperäiset poistuvat lähteestä)"
                    ).grid(row=3, column=0, columnspan=3, sticky="w")

    b = ttk.Frame(f)
    b.grid(row=3, column=0, columnspan=3, sticky="w")
    btn_prev = ttk.Button(b, text="Esikatsele")
    btn_run = ttk.Button(b, text="Lajittele")
    btn_prev.pack(side="left")
    btn_run.pack(side="left", padx=8)

    pb = ttk.Progressbar(f, mode="determinate")
    pb.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
    txt = tk.Text(f, height=14, wrap="word", state="disabled")
    txt.grid(row=5, column=0, columnspan=3, sticky="nsew")
    sb = ttk.Scrollbar(f, command=txt.yview)
    sb.grid(row=5, column=3, sticky="ns")
    txt["yscrollcommand"] = sb.set
    f.rowconfigure(5, weight=1)

    def loki(s):
        jono.put(("log", s))

    def edistyy(a, b_):
        jono.put(("pb", (a, b_)))

    def poll():
        try:
            while True:
                k, v = jono.get_nowait()
                if k == "log":
                    txt.config(state="normal")
                    txt.insert("end", v + "\n")
                    txt.see("end")
                    txt.config(state="disabled")
                elif k == "pb":
                    pb["maximum"] = max(v[1], 1)
                    pb["value"] = v[0]
                elif k == "done":
                    ty["käy"] = False
                    btn_prev.config(state="normal")
                    btn_run.config(state="normal")
        except queue.Empty:
            pass
        root.after(100, poll)

    def käynnistä(suorita_oikeasti):
        l, k = lahde.get().strip(), kohde.get().strip()
        if not os.path.isdir(l):
            messagebox.showerror("KuvaLajittelija", "Valitse lähdekansio.")
            return
        if not k:
            messagebox.showerror("KuvaLajittelija", "Valitse kohdekansio.")
            return
        try:
            kb = int(pieni.get() or 0)
        except ValueError:
            messagebox.showerror("KuvaLajittelija", "Pienen kuvan raja on kokonaisluku (kt).")
            return
        if suorita_oikeasti and siirra.get() and not messagebox.askyesno(
                "Vahvista", "Tiedostot SIIRRETÄÄN lähdekansiosta. Jatketaan?"):
            return
        btn_prev.config(state="disabled")
        btn_run.config(state="disabled")
        pb["value"] = 0
        sm, ss = samann.get(), siirra.get()

        def työ():
            try:
                loki("--- %s %s ---" % ("Lajittelu" if suorita_oikeasti else "Esikatselu",
                                         datetime.now().strftime("%H:%M:%S")))
                sunn, t = suunnittele(l, k, kb, sm, loki, edistyy)
                loki("Duplikaatteja: %d, pieniä kuvia: %d, normaaleja: %d"
                     % (t["duplikaatit"], t["pienet"], t["yhteensä"] - t["duplikaatit"] - t["pienet"]))
                if suorita_oikeasti:
                    v = suorita(sunn, k, ss, loki, edistyy)
                    loki("Valmis. Käsiteltiin %d tiedostoa, virheitä %d." % (len(sunn), v))
                else:
                    for s, r, c in sunn[:30]:
                        loki("  %s → %s" % (os.path.basename(s), r or "."))
                    if len(sunn) > 30:
                        loki("  … ja %d muuta" % (len(sunn) - 30))
            except Exception as e:
                loki("VIRHE: %s" % e)
            jono.put(("done", None))

        ty["käy"] = True
        threading.Thread(target=työ, daemon=True).start()

    btn_prev.config(command=lambda: käynnistä(False))
    btn_run.config(command=lambda: käynnistä(True))
    poll()
    root.mainloop()


if __name__ == "__main__":
    gui()
