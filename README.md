# OLX Mac mini watcher

Svakih 5 min (GitHub Actions) provjerava OLX.ba za povoljne Mac mini (M1–M6) oglase i šalje push notifikaciju preko [ntfy](https://ntfy.sh).

- `watcher.py` – pretraga + filter. Pragovi cijena (`MAX_PRICE`) i riječi za izbacivanje (`EXCLUDE`) su na vrhu fajla.
- `seen.json` – ID-jevi već viđenih oglasa (workflow ga sam ažurira).
- ntfy topic je u secretu `NTFY_TOPIC`.

Ručno pokretanje: Actions → *OLX Mac mini watcher* → Run workflow.
Lokalno: `NTFY_TOPIC=... python3 watcher.py --loop`
