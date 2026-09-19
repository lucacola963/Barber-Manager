from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path


app = Flask(__name__)


# =========================================================
# CONFIGURAZIONE
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "barber.db"

BACKUP_DIR = BASE_DIR / "backup"
MAX_BACKUPS = 30


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")

    return conn


def init_db():

    conn = get_db()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS collaboratori (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            attivo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS servizi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            prezzo REAL NOT NULL,
            attivo INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS registrazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_ora TEXT NOT NULL,
            collaboratore_id INTEGER NOT NULL,
            servizio_id INTEGER NOT NULL,
            collaboratore_nome TEXT NOT NULL,
            servizio_nome TEXT NOT NULL,
            prezzo_applicato REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_registrazioni_data_ora
        ON registrazioni(data_ora);

        CREATE INDEX IF NOT EXISTS idx_registrazioni_collaboratore
        ON registrazioni(collaboratore_id);

        CREATE INDEX IF NOT EXISTS idx_registrazioni_servizio
        ON registrazioni(servizio_id);

        CREATE INDEX IF NOT EXISTS idx_registrazioni_data_collaboratore
        ON registrazioni(data_ora, collaboratore_id);

        CREATE INDEX IF NOT EXISTS idx_registrazioni_data_servizio
        ON registrazioni(data_ora, servizio_id);
    """)

    # -----------------------------------------------------
    # DATI INIZIALI COLLABORATORI
    # -----------------------------------------------------

    if conn.execute(
        "SELECT COUNT(*) FROM collaboratori"
    ).fetchone()[0] == 0:

        conn.executemany(
            """
            INSERT INTO collaboratori (nome)
            VALUES (?)
            """,
            [
                ("Antonio",),
                ("Giuseppe",),
                ("Mario",)
            ]
        )

    # -----------------------------------------------------
    # DATI INIZIALI SERVIZI
    # -----------------------------------------------------

    if conn.execute(
        "SELECT COUNT(*) FROM servizi"
    ).fetchone()[0] == 0:

        conn.executemany(
            """
            INSERT INTO servizi (nome, prezzo)
            VALUES (?, ?)
            """,
            [
                ("Barba", 12),
                ("Taglio", 20),
                ("Taglio + Barba", 28),
                ("Trattamento", 15)
            ]
        )

    conn.commit()
    conn.close()


# =========================================================
# BACKUP
# =========================================================

def crea_backup():

    try:

        # -------------------------------------------------
        # CREA CARTELLA BACKUP SE NON ESISTE
        # -------------------------------------------------

        BACKUP_DIR.mkdir(
            parents=True,
            exist_ok=True
        )

        # -------------------------------------------------
        # CONTROLLO BACKUP DEL GIORNO
        # -------------------------------------------------

        oggi = date.today().isoformat()

        backup_del_giorno = list(
            BACKUP_DIR.glob(
                f"backup_{oggi}_*.db"
            )
        )

        # Se esiste già un backup di oggi,
        # non ne creiamo un altro.
        if backup_del_giorno:
            pulisci_backup_vecchi()
            return True

        # -------------------------------------------------
        # NOME BACKUP
        # -------------------------------------------------

        timestamp = datetime.now().strftime(
            "%Y-%m-%d_%H%M%S"
        )

        backup_file = (
            BACKUP_DIR /
            f"backup_{timestamp}.db"
        )

        # File temporaneo.
        # In caso di errore viene eliminato.
        backup_temp = (
            BACKUP_DIR /
            f".backup_temp_{timestamp}.db"
        )

        # -------------------------------------------------
        # BACKUP SQLITE NATIVO
        # -------------------------------------------------

        origine = None
        destinazione = None

        try:

            origine = sqlite3.connect(
                DATABASE
            )

            destinazione = sqlite3.connect(
                backup_temp
            )

            origine.backup(
                destinazione
            )

            destinazione.commit()

        finally:

            if origine is not None:
                origine.close()

            if destinazione is not None:
                destinazione.close()

        # -------------------------------------------------
        # RINOMINA FILE TEMPORANEO
        # -------------------------------------------------

        backup_temp.replace(
            backup_file
        )

        # -------------------------------------------------
        # ELIMINA BACKUP VECCHI
        # -------------------------------------------------

        pulisci_backup_vecchi()

        return True

    except Exception as e:

        print(
            f"[BACKUP] Errore durante il backup: {e}"
        )

        # Elimina eventuale file temporaneo
        # rimasto dopo un errore.

        try:

            if "backup_temp" in locals():
                if backup_temp.exists():
                    backup_temp.unlink()

        except Exception:
            pass

        return False


def pulisci_backup_vecchi():

    try:

        backup_files = sorted(
            BACKUP_DIR.glob("backup_*.db"),
            key=lambda file: file.stat().st_mtime,
            reverse=True
        )

        # Manteniamo solamente gli ultimi 30.
        for vecchio_backup in backup_files[MAX_BACKUPS:]:

            try:
                vecchio_backup.unlink()

            except Exception as e:

                print(
                    "[BACKUP] "
                    f"Impossibile eliminare "
                    f"{vecchio_backup.name}: {e}"
                )

    except Exception as e:

        print(
            f"[BACKUP] Errore pulizia backup: {e}"
        )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    conn = get_db()

    # -----------------------------------------------------
    # COLLABORATORI ATTIVI
    # -----------------------------------------------------

    collaboratori = conn.execute("""
        SELECT
            id,
            nome
        FROM collaboratori
        WHERE attivo = 1
        ORDER BY nome
    """).fetchall()

    # -----------------------------------------------------
    # SERVIZI ATTIVI
    # -----------------------------------------------------

    servizi = conn.execute("""
        SELECT
            id,
            nome,
            prezzo
        FROM servizi
        WHERE attivo = 1
        ORDER BY nome
    """).fetchall()

    # -----------------------------------------------------
    # DATA ODIERNA
    # -----------------------------------------------------

    oggi = date.today().isoformat()

    domani = (
        date.today() +
        timedelta(days=1)
    ).isoformat()

    # -----------------------------------------------------
    # STATISTICHE ODIERNE
    # -----------------------------------------------------

    statistiche = conn.execute("""
        SELECT
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE data_ora >= ?
        AND data_ora < ?
    """, (
        oggi + " 00:00:00",
        domani + " 00:00:00"
    )).fetchone()

    ticket_medio = 0

    if statistiche["numero"] > 0:

        ticket_medio = (
            statistiche["totale"] /
            statistiche["numero"]
        )

    # -----------------------------------------------------
    # OGGI PER OPERATORE
    # -----------------------------------------------------

    per_operatore = conn.execute("""
        SELECT
            collaboratore_nome,
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE data_ora >= ?
        AND data_ora < ?
        GROUP BY
            collaboratore_id,
            collaboratore_nome
        ORDER BY totale DESC
    """, (
        oggi + " 00:00:00",
        domani + " 00:00:00"
    )).fetchall()

    # -----------------------------------------------------
    # ULTIME 5 REGISTRAZIONI
    # -----------------------------------------------------

    recenti = conn.execute("""
        SELECT
            id,
            data_ora,
            collaboratore_nome,
            servizio_nome,
            prezzo_applicato
        FROM registrazioni
        ORDER BY id DESC
        LIMIT 5
    """).fetchall()

    conn.close()

    return render_template(
        "index.html",
        collaboratori=collaboratori,
        servizi=servizi,
        statistiche=statistiche,
        ticket_medio=ticket_medio,
        per_operatore=per_operatore,
        recenti=recenti
    )


# =========================================================
# REGISTRA SERVIZIO
# =========================================================

@app.post("/registra")
def registra():

    cid = request.form.get(
        "collaboratore",
        type=int
    )

    sid = request.form.get(
        "servizio",
        type=int
    )

    if not cid or not sid:
        return redirect(url_for("home"))

    conn = get_db()

    collaboratore = conn.execute("""
        SELECT
            id,
            nome
        FROM collaboratori
        WHERE id = ?
        AND attivo = 1
    """, (cid,)).fetchone()

    servizio = conn.execute("""
        SELECT
            id,
            nome,
            prezzo
        FROM servizi
        WHERE id = ?
        AND attivo = 1
    """, (sid,)).fetchone()

    if collaboratore and servizio:

        conn.execute("""
            INSERT INTO registrazioni (
                data_ora,
                collaboratore_id,
                servizio_id,
                collaboratore_nome,
                servizio_nome,
                prezzo_applicato
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            collaboratore["id"],
            servizio["id"],
            collaboratore["nome"],
            servizio["nome"],
            servizio["prezzo"]
        ))

        conn.commit()

    conn.close()

    return redirect(url_for("home"))


# =========================================================
# LISTINO
# =========================================================

@app.route("/listino")
def listino():

    conn = get_db()

    servizi = conn.execute("""
        SELECT
            id,
            nome,
            prezzo,
            attivo
        FROM servizi
        ORDER BY attivo DESC, nome
    """).fetchall()

    conn.close()

    return render_template(
        "listino.html",
        servizi=servizi
    )


@app.post("/listino/aggiungi")
def aggiungi_servizio():

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    raw = request.form.get(
        "prezzo",
        ""
    ).replace(",", ".")

    try:
        prezzo = float(raw)

    except ValueError:
        return redirect(url_for("listino"))

    if nome and prezzo >= 0:

        conn = get_db()

        conn.execute("""
            INSERT INTO servizi (
                nome,
                prezzo,
                attivo
            )
            VALUES (?, ?, 1)
        """, (
            nome,
            prezzo
        ))

        conn.commit()
        conn.close()

    return redirect(url_for("listino"))


@app.post("/listino/<int:id>/modifica")
def modifica_servizio(id):

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    raw = request.form.get(
        "prezzo",
        ""
    ).replace(",", ".")

    try:
        prezzo = float(raw)

    except ValueError:
        return redirect(url_for("listino"))

    if nome and prezzo >= 0:

        conn = get_db()

        conn.execute("""
            UPDATE servizi
            SET
                nome = ?,
                prezzo = ?
            WHERE id = ?
        """, (
            nome,
            prezzo,
            id
        ))

        conn.commit()
        conn.close()

    return redirect(url_for("listino"))


@app.post("/listino/<int:id>/toggle")
def toggle_servizio(id):

    conn = get_db()

    conn.execute("""
        UPDATE servizi
        SET attivo =
            CASE
                WHEN attivo = 1 THEN 0
                ELSE 1
            END
        WHERE id = ?
    """, (id,))

    conn.commit()
    conn.close()

    return redirect(url_for("listino"))


# =========================================================
# STAFF
# =========================================================

@app.route("/staff")
def staff():

    conn = get_db()

    collaboratori = conn.execute("""
        SELECT
            id,
            nome,
            attivo
        FROM collaboratori
        ORDER BY attivo DESC, nome
    """).fetchall()

    conn.close()

    return render_template(
        "staff.html",
        collaboratori=collaboratori
    )


@app.post("/staff/aggiungi")
def aggiungi_collaboratore():

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    if nome:

        conn = get_db()

        conn.execute("""
            INSERT INTO collaboratori (
                nome,
                attivo
            )
            VALUES (?, 1)
        """, (nome,))

        conn.commit()
        conn.close()

    return redirect(url_for("staff"))


@app.post("/staff/<int:id>/modifica")
def modifica_collaboratore(id):

    nome = request.form.get(
        "nome",
        ""
    ).strip()

    if nome:

        conn = get_db()

        conn.execute("""
            UPDATE collaboratori
            SET nome = ?
            WHERE id = ?
        """, (
            nome,
            id
        ))

        conn.commit()
        conn.close()

    return redirect(url_for("staff"))


@app.post("/staff/<int:id>/toggle")
def toggle_collaboratore(id):

    conn = get_db()

    conn.execute("""
        UPDATE collaboratori
        SET attivo =
            CASE
                WHEN attivo = 1 THEN 0
                ELSE 1
            END
        WHERE id = ?
    """, (id,))

    conn.commit()
    conn.close()

    return redirect(url_for("staff"))


# =========================================================
# BACKUP MANUALE
# =========================================================

@app.post("/backup")
def backup_manuale():

    successo = crea_backup()

    if successo:
        return redirect(
            url_for(
                "staff",
                backup="ok"
            )
        )

    return redirect(
        url_for(
            "staff",
            backup="errore"
        )
    )


# =========================================================
# REPORT / STORICO
# =========================================================

@app.route("/storico")
def storico():

    conn = get_db()

    # -----------------------------------------------------
    # FILTRI
    # -----------------------------------------------------

    collaboratori = conn.execute("""
        SELECT
            id,
            nome
        FROM collaboratori
        ORDER BY nome
    """).fetchall()

    servizi = conn.execute("""
        SELECT
            id,
            nome
        FROM servizi
        ORDER BY nome
    """).fetchall()

    oggi = date.today()

    default_da = (
        oggi -
        timedelta(days=29)
    ).isoformat()

    default_al = oggi.isoformat()

    dal = request.args.get(
        "dal",
        default_da
    )

    al = request.args.get(
        "al",
        default_al
    )

    operatore = request.args.get(
        "operatore",
        type=int
    )

    servizio = request.args.get(
        "servizio",
        type=int
    )

    # -----------------------------------------------------
    # VALIDAZIONE DATE
    # -----------------------------------------------------

    try:

        data_da = date.fromisoformat(dal)
        data_al = date.fromisoformat(al)

        if data_da > data_al:

            data_da, data_al = (
                data_al,
                data_da
            )

            dal = data_da.isoformat()
            al = data_al.isoformat()

    except ValueError:

        dal = default_da
        al = default_al

        data_da = date.fromisoformat(dal)
        data_al = date.fromisoformat(al)

    # -----------------------------------------------------
    # INTERVALLO DATE
    # -----------------------------------------------------

    data_inizio = (
        data_da.isoformat() +
        " 00:00:00"
    )

    data_fine_esclusiva = (
        (
            data_al +
            timedelta(days=1)
        ).isoformat() +
        " 00:00:00"
    )

    where = """
        data_ora >= ?
        AND data_ora < ?
    """

    params = [
        data_inizio,
        data_fine_esclusiva
    ]

    if operatore:

        where += """
            AND collaboratore_id = ?
        """

        params.append(
            operatore
        )

    if servizio:

        where += """
            AND servizio_id = ?
        """

        params.append(
            servizio
        )

    # -----------------------------------------------------
    # KPI PRINCIPALI
    # -----------------------------------------------------

    riepilogo = conn.execute(f"""
        SELECT
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE {where}
    """, params).fetchone()

    ticket_medio = 0

    if riepilogo["numero"] > 0:

        ticket_medio = (
            riepilogo["totale"] /
            riepilogo["numero"]
        )

    # -----------------------------------------------------
    # PERFORMANCE OPERATORI
    # -----------------------------------------------------

    per_operatore = conn.execute(f"""
        SELECT
            collaboratore_nome,
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE {where}
        GROUP BY
            collaboratore_id,
            collaboratore_nome
        ORDER BY totale DESC
    """, params).fetchall()

    # -----------------------------------------------------
    # PERFORMANCE SERVIZI
    # -----------------------------------------------------

    per_servizio = conn.execute(f"""
        SELECT
            servizio_nome,
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE {where}
        GROUP BY
            servizio_id,
            servizio_nome
        ORDER BY totale DESC
    """, params).fetchall()

    # -----------------------------------------------------
    # ANDAMENTO GIORNALIERO
    # -----------------------------------------------------

    dati_giornalieri = conn.execute(f"""
        SELECT
            substr(data_ora, 1, 10) AS giorno,
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE {where}
        GROUP BY substr(data_ora, 1, 10)
        ORDER BY giorno
    """, params).fetchall()

    # -----------------------------------------------------
    # COMPLETIAMO I GIORNI SENZA REGISTRAZIONI
    # -----------------------------------------------------

    giornalieri_db = {}

    for r in dati_giornalieri:

        giornalieri_db[
            r["giorno"]
        ] = {
            "numero": r["numero"],
            "totale": float(r["totale"])
        }

    andamento_giornaliero = []

    giorno_corrente = data_da

    while giorno_corrente <= data_al:

        giorno_str = giorno_corrente.isoformat()

        valori = giornalieri_db.get(
            giorno_str,
            {
                "numero": 0,
                "totale": 0
            }
        )

        andamento_giornaliero.append({
            "giorno": giorno_str,
            "numero": valori["numero"],
            "totale": valori["totale"]
        })

        giorno_corrente += timedelta(days=1)

    # -----------------------------------------------------
    # ANDAMENTO SETTIMANALE
    # -----------------------------------------------------

    settimane = {}

    for r in andamento_giornaliero:

        giorno = date.fromisoformat(
            r["giorno"]
        )

        lunedi = (
            giorno -
            timedelta(
                days=giorno.weekday()
            )
        )

        chiave = lunedi.isoformat()

        if chiave not in settimane:

            settimane[chiave] = {
                "numero": 0,
                "totale": 0
            }

        settimane[chiave]["numero"] += (
            r["numero"]
        )

        settimane[chiave]["totale"] += (
            r["totale"]
        )

    andamento_settimanale = []

    for chiave in sorted(settimane):

        andamento_settimanale.append({
            "periodo": chiave,
            "numero": settimane[chiave]["numero"],
            "totale": settimane[chiave]["totale"]
        })

    # -----------------------------------------------------
    # ANDAMENTO MENSILE
    # -----------------------------------------------------

    mesi = {}

    for r in andamento_giornaliero:

        mese = r["giorno"][:7]

        if mese not in mesi:

            mesi[mese] = {
                "numero": 0,
                "totale": 0
            }

        mesi[mese]["numero"] += (
            r["numero"]
        )

        mesi[mese]["totale"] += (
            r["totale"]
        )

    andamento_mensile = []

    for mese in sorted(mesi):

        andamento_mensile.append({
            "periodo": mese,
            "numero": mesi[mese]["numero"],
            "totale": mesi[mese]["totale"]
        })

    # -----------------------------------------------------
    # PERIODO PRECEDENTE
    # -----------------------------------------------------

    giorni_periodo = (
        data_al -
        data_da
    ).days + 1

    precedente_al = (
        data_da -
        timedelta(days=1)
    )

    precedente_da = (
        precedente_al -
        timedelta(
            days=giorni_periodo - 1
        )
    )

    precedente_inizio = (
        precedente_da.isoformat() +
        " 00:00:00"
    )

    precedente_fine_esclusiva = (
        (
            precedente_al +
            timedelta(days=1)
        ).isoformat() +
        " 00:00:00"
    )

    precedente = conn.execute("""
        SELECT
            COUNT(*) AS numero,
            COALESCE(
                SUM(prezzo_applicato),
                0
            ) AS totale
        FROM registrazioni
        WHERE data_ora >= ?
        AND data_ora < ?
    """, (
        precedente_inizio,
        precedente_fine_esclusiva
    )).fetchone()

    # -----------------------------------------------------
    # VARIAZIONI
    # -----------------------------------------------------

    variazione_servizi = None
    variazione_valore = None

    if precedente["numero"] > 0:

        variazione_servizi = (
            (
                riepilogo["numero"] -
                precedente["numero"]
            )
            /
            precedente["numero"]
        ) * 100

    if precedente["totale"] > 0:

        variazione_valore = (
            (
                riepilogo["totale"] -
                precedente["totale"]
            )
            /
            precedente["totale"]
        ) * 100

    # -----------------------------------------------------
    # DETTAGLIO
    # -----------------------------------------------------

    dettagli = conn.execute(f"""
        SELECT
            id,
            data_ora,
            collaboratore_nome,
            servizio_nome,
            prezzo_applicato
        FROM registrazioni
        WHERE {where}
        ORDER BY data_ora DESC
        LIMIT 5000
    """, params).fetchall()

    conn.close()

    # -----------------------------------------------------
    # RENDER
    # -----------------------------------------------------

    return render_template(
        "storico.html",

        collaboratori=collaboratori,
        servizi=servizi,

        operatore=operatore,
        servizio=servizio,

        dal=dal,
        al=al,

        riepilogo=riepilogo,
        ticket_medio=ticket_medio,

        per_operatore=per_operatore,
        per_servizio=per_servizio,

        andamento_giornaliero=andamento_giornaliero,
        andamento_settimanale=andamento_settimanale,
        andamento_mensile=andamento_mensile,

        variazione_servizi=variazione_servizi,
        variazione_valore=variazione_valore,

        dettagli=dettagli
    )


# =========================================================
# INIZIALIZZAZIONE
# =========================================================

init_db()


# =========================================================
# BACKUP AUTOMATICO
# =========================================================

crea_backup()


# =========================================================
# AVVIO
# =========================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False
    )