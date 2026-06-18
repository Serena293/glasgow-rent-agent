# Glasgow Rent Agent

Agent locale per trovare flat arredati a Glasgow e inviare due digest email:

- 08:30 Europe/London: invia sempre il riepilogo, anche vuoto.
- 18:00 Europe/London: invia solo se ci sono nuovi annunci o cali prezzo.

## Criteri iniziali

- Affitto.
- Glasgow.
- Max GBP 900 pcm.
- Minimo 1 bedroom.
- Intero flat/apartment, non stanza.
- Furnished o part-furnished.
- Zone: G11, G3 8, G41.
- Esclude student-only, sublet, short let, room/share e unfurnished.
- Prima baseline: gli annunci gia online vengono segnati come gia visti, quindi ricevi solo annunci nuovi.

## Setup locale

```powershell
cd glasgow-rent-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

## Gmail API

1. Crea un progetto su Google Cloud.
2. Abilita Gmail API.
3. Crea OAuth client ID di tipo "Desktop app".
4. Scarica il file JSON e salvalo come `credentials.json` nella root del progetto.
5. Al primo invio, il comando aprira il browser per autorizzare Gmail.

Il token locale viene salvato in `.secrets/gmail_token.json` ed e ignorato da git.

## Comandi

Inizializza il database:

```powershell
house-agent init-db
```

Crea la baseline senza inviare email:

```powershell
house-agent baseline
```

Per testare una fonte alla volta:

```powershell
house-agent check --source openrent --no-detail
```

Vedi eventuali annunci pendenti:

```powershell
house-agent show-pending
```

Invia una email di prova:

```powershell
house-agent email-test
```

Genera una preview HTML senza inviare:

```powershell
house-agent morning --dry-run
house-agent evening --dry-run
```

Se vuoi provare una corsa veloce mentre fai debug:

```powershell
house-agent morning --dry-run --source openrent --no-detail
```

Esecuzione reale:

```powershell
house-agent morning
house-agent evening
```

## Deploy Render dopo la prova locale

Per Render usa `render.yaml`: crea un Cron Job e un database Postgres. I Cron Job di Render non hanno persistent disk, quindi SQLite va bene in locale ma non in produzione.

Vedi [RENDER.md](RENDER.md) per i passaggi.
