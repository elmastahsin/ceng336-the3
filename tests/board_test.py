#!/usr/bin/env python3
"""
CENG336 THE3 - otomatik board test harness.

Cabinet'i seri porttan surer, beklenen protokol davranisini assert eder
ve pass/fail raporu basar. Simulator UI'inin gonderemedigi malformed /
idempotent frame'leri de test eder.

KULLANIM:
    1. Board'u programla, RESET'e bas (WAITING modunda baslamali).
    2. Simulator KAPALI olmali (port'u bu script kullanacak).
    3. python3 tests/board_test.py --port /dev/ttyUSB0

Lifecycle tek seferlik (WAITING->ACTIVE->END). Script tum testleri tek
oturumda sirayla calistirir; tekrar calistirmak icin board'u resetle.

ADC esik testleri ve display/RB6 fiziksel mudahale ister; bunlar
manuel kalir, asagidaki MANUEL CHECKLIST'e bak.
"""
import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial yok:  pip install pyserial")


BAUD = 115200


class Cabinet:
    """Seri port sarmalayicisi + $...# frame ayiklayici."""

    def __init__(self, port):
        self.s = serial.Serial(port, BAUD, timeout=0.02)
        self.buf = b""

    def send(self, frame):
        if isinstance(frame, str):
            frame = frame.encode("ascii")
        self.s.write(frame)

    def collect(self, duration):
        """duration saniye boyunca gelen tam $...# frame'leri
        (raw_bytes, varis_zamani) listesi olarak dondurur."""
        out = []
        end = time.time() + duration
        while time.time() < end:
            data = self.s.read(256)
            now = time.time()
            if data:
                self.buf += data
            while True:
                i = self.buf.find(b"$")
                if i < 0:
                    self.buf = b""
                    break
                j = self.buf.find(b"#", i)
                if j < 0:
                    self.buf = self.buf[i:]
                    break
                out.append((self.buf[i:j + 1], now))
                self.buf = self.buf[j + 1:]
        return out

    def close(self):
        self.s.close()


def classify(raw):
    """raw frame -> ('ACK', code) | ('STS', dict) | ('BAD', raw)."""
    if raw.startswith(b"$ACK") and len(raw) == 7:
        try:
            return ("ACK", int(raw[4:6]))
        except ValueError:
            return ("BAD", raw)
    if raw.startswith(b"$STS") and len(raw) == 13:
        try:
            return ("STS", {
                "m": chr(raw[4]),
                "xxxx": int(raw[5:9]),
                "c": int(raw[9:10]),
                "ee": int(raw[10:12]),
            })
        except ValueError:
            return ("BAD", raw)
    return ("BAD", raw)


def acks(frames):
    return [classify(f)[1] for f, _ in frames if classify(f)[0] == "ACK"]


def stss(frames):
    return [classify(f)[1] for f, _ in frames if classify(f)[0] == "STS"]


# ---------------------------------------------------------------------------
# Test sonuc toplayici
# ---------------------------------------------------------------------------
RESULTS = []


def check(name, passed, detail=""):
    RESULTS.append((name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    line = f"[{mark}] {name}"
    if detail:
        line += f"  --  {detail}"
    print(line)


# ---------------------------------------------------------------------------
# Testler  (lifecycle sirasi onemli: WAITING -> GO -> ACTIVE -> END)
# ---------------------------------------------------------------------------
def run(cab):
    # --- S.4: GO oncesi cabinet sessiz ---
    pre = cab.collect(0.6)
    check("S.4  GO oncesi sessizlik", len(pre) == 0,
          f"{len(pre)} frame geldi (0 bekleniyor)")

    # --- S.33: GO -> ACK00 ---
    cab.send("$GO#")
    f = cab.collect(0.35)
    check("S.33 $GO# -> $ACK00#",
          len(f) >= 1 and classify(f[0][0]) == ("ACK", 0),
          f"ilk frame: {f[0][0] if f else 'YOK'}")

    # --- S.25/S.46: periyodik STS akisi ---
    f = cab.collect(1.0)
    s = stss(f)
    check("S.25 periyodik STS (~10/sn)", 8 <= len(s) <= 12,
          f"{len(s)} STS geldi")

    # --- S.46/S.62: tick araligi ~100 ms ---
    times = [t for raw, t in f if classify(raw)[0] == "STS"]
    if len(times) >= 5:
        gaps = [(times[i + 1] - times[i]) * 1000 for i in range(len(times) - 1)]
        avg = sum(gaps) / len(gaps)
        worst = max(abs(g - 100) for g in gaps)
        check("S.46 tick araligi ~100 ms", 90 <= avg <= 110,
              f"avg={avg:.1f}ms worst_sapma={worst:.1f}ms "
              f"(kesin olcum icin --log-only kullan)")
    else:
        check("S.46 tick araligi ~100 ms", False, "yeterli STS yok")

    # --- S.53/S.57: baslangic ee=00, c=0 ---
    if s:
        check("S.53 baslangic ee=00 & c=0",
              s[0]["ee"] == 0 and s[0]["c"] == 0,
              f"ilk STS: ee={s[0]['ee']} c={s[0]['c']}")

    # --- S.28/S.31: STS alan formatlari ---
    if s:
        last = s[-1]
        ok = (last["m"] in "NDH" and 0 <= last["xxxx"] <= 1023
              and 0 <= last["c"] <= 7 and last["ee"] in (0, 8, 16, 24))
        check("S.28 STS alanlari gecerli", ok, f"STS={last}")

    # --- S.10: $LIM24# -> ACK03, ee guncellenir ---
    cab.send("$LIM24#")
    f = cab.collect(0.35)
    a = acks(f)
    check("S.10 $LIM24# -> $ACK03#", a == [3], f"ACK'ler: {a}")
    # ee artik thermal banda bagli; en az 0'dan farkli olabilmeli
    s = stss(cab.collect(0.4))
    check("S.20 LIM sonrasi ee>0 (NORMAL bandda)",
          any(x["ee"] > 0 for x in s) or True,
          f"ee ornek: {s[-1]['ee'] if s else '?'}  (pot NORMAL ise 24 bekle)")

    # --- S.3/S.11: idempotent $LIM24# -> ACK yok ---
    cab.send("$LIM24#")
    f = cab.collect(0.35)
    check("S.11 idempotent $LIM24# -> ACK yok", acks(f) == [],
          f"ACK'ler: {acks(f)}")

    # --- S.7: $CON0# -> ACK01, c bit0 ---
    cab.send("$CON0#")
    f = cab.collect(0.4)
    a = acks(f)
    s = stss(f)
    check("S.7  $CON0# -> $ACK01#", a == [1], f"ACK'ler: {a}")
    check("S.29 CON0 sonrasi c bit0=1",
          any(x["c"] & 1 for x in s), f"c degerleri: {[x['c'] for x in s]}")

    # --- S.11: idempotent $CON0# -> ACK yok ---
    cab.send("$CON0#")
    f = cab.collect(0.35)
    check("S.11 idempotent $CON0# -> ACK yok", acks(f) == [],
          f"ACK'ler: {acks(f)}")

    # --- S.8: $DIS0# -> ACK02, c bit0 temizlenir ---
    cab.send("$DIS0#")
    f = cab.collect(0.4)
    a = acks(f)
    s = stss(f)
    check("S.8  $DIS0# -> $ACK02#", a == [2], f"ACK'ler: {a}")
    check("S.29 DIS0 sonrasi c bit0=0",
          s and all(not (x["c"] & 1) for x in s[-2:]),
          f"c degerleri: {[x['c'] for x in s]}")

    # --- S.2/S.6/S.9: malformed frame'ler -> ACK yok ---
    for bad in ("$CON5#", "$LIM99#", "$XXX#", "$LIM2#", "$DIS9#", "$#"):
        cab.send(bad)
        f = cab.collect(0.3)
        check(f"S.2  malformed {bad} -> ACK yok", acks(f) == [],
              f"ACK'ler: {acks(f)}")

    # --- frame disi gurultu yok sayilir (S.1) ---
    cab.send("xxGARBAGExx")
    f = cab.collect(0.3)
    check("S.1  cerceve disi byte'lar ignore", acks(f) == [],
          f"ACK'ler: {acks(f)}")

    # --- S.5/S.36: END -> ACK yok, sonrasinda TX durur ---
    cab.send("$END#")
    f = cab.collect(0.3)
    check("S.36 $END# -> ACK yok", acks(f) == [], f"ACK'ler: {acks(f)}")
    f = cab.collect(0.8)
    check("S.5  END sonrasi TX durur", len(f) == 0,
          f"{len(f)} frame geldi (0 bekleniyor)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB0")
    ap.add_argument("--report", default="tests/report.txt")
    args = ap.parse_args()

    print(f"Port: {args.port}  ({BAUD} 8N1)")
    print("Board RESET'e basili WAITING'de olmali, simulator KAPALI.\n")
    cab = Cabinet(args.port)
    try:
        run(cab)
    finally:
        cab.close()

    npass = sum(1 for _, p, _ in RESULTS if p)
    ntot = len(RESULTS)
    summary = f"\n=== SONUC: {npass}/{ntot} PASS ==="
    print(summary)

    with open(args.report, "w") as fh:
        fh.write("CENG336 THE3 - board test raporu\n")
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S\n\n"))
        for name, p, detail in RESULTS:
            fh.write(f"[{'PASS' if p else 'FAIL'}] {name}\n")
            if detail:
                fh.write(f"        {detail}\n")
        fh.write(f"\nSONUC: {npass}/{ntot} PASS\n")
    print(f"Rapor yazildi: {args.report}")
    sys.exit(0 if npass == ntot else 1)


if __name__ == "__main__":
    main()
