# Decision Log: Aufräumen der Basis und Mileage-Run-Features

Stand: 2026-11-27 · Autor: Jens Wetterich (mit Claude)

Entscheidungen, die Claude getroffen hat und die nicht ausdrücklich von
mir kommen, sind mit **(Claudes Entscheidung)** markiert.

## Kontext und Ziel

`flight-search` ist das Tool eines Freundes (Wochenend- und Open-Jaw-Suche
ab Karlsruhe über Google Flights via `fli`). Ich will es ab München nutzen
und für **Mileage Runs mit Aegean** erweitern: möglichst viele
Aegean-Segmente (A3 und Olympic Air OA zählen beide), seltener Meilen,
verpackt in eine sinnvolle, günstige Urlaubskombination.

Typische Reisen:

- MUC → Zypern → MUC, nur Aegean/Olympic.
- MUC → Zypern → Rhodos → Karpathos → Sitia → MUC. Diese Kette plane ich
  **selbst Schritt für Schritt**. Das Tool soll mir pro Schritt den
  günstigsten passenden Flug liefern, nicht die ganze Kette optimieren.

Erfolg heißt: Ich kann mit wenigen Aufrufen (1) einen Hin- und Rückflug
bzw. Gabelflug ab MUC nur mit Aegean finden und (2) ab einem Ort auf der
Reise den günstigsten Aegean-Weiterflug in eine Zielauswahl, und ich sehe
dabei Umsteigeverbindungen klar.

## Ziele, Nicht-Ziele, Anti-Ziele

**Ziele**

- Basis aufräumen, sodass neue Suchtypen ohne Kopieren der CLI-Logik
  möglich sind.
- Wohnort und Defaults konfigurierbar, ohne Code zu ändern.
- Airline-Filter, Einweg-Weiterflugsuche, Gabelflug über verschiedene
  Städte, gute Darstellung von Umsteigeverbindungen.
- Zum Schluss ein interaktiver Terminal-Modus zum Durchklicken der
  Ergebnisse.

**Nicht-Ziele**

- Automatische Planung ganzer Ketten mit mehreren Zielen.
- Preis pro Segment als Kennzahl oder Sortierung.
- Meilen- oder Statuspunkte-Berechnung, Prämienflüge, Buchung.

**Anti-Ziele** (wäre ein Fehlschlag, auch wenn es technisch funktioniert)

- Das bestehende Verhalten für meinen Freund ändert sich unbemerkt
  (Defaults Karlsruhe, `FKB,STR,SXB,FRA`, Ausgabe, Request-Zahlen).
- PRs, die Refactoring und Features mischen, sodass er sie nicht
  einzeln prüfen oder ablehnen kann.
- Das Tool schickt deutlich mehr Requests an Google als nötig und wird
  gedrosselt.

## Rahmenbedingungen

- Google akzeptiert höchstens **14 Flughäfen pro Request** (Heimat + Ziele
  zusammen). Daraus folgt die Batch-Größe in Phase 1.
- `fli` ist auf einen Git-Commit gepinnt. `links.py` nutzt das private
  Modul `fli.search._proto`. Kein Upgrade von `fli` in diesem Vorhaben.
- `fli` kann bereits `airlines`, `airlines_exclude`, `alliances`,
  `alliances_exclude`, `layover_restrictions` und `max_duration` in
  `FlightSearchFilters`. Das Tool reicht sie heute nicht durch. `A3` und
  `OA` sind im `Airline`-Enum vorhanden.
- Tests bleiben vollständig offline (kein Netz in `pytest`).
- Python ≥ 3.12, `uv`, Abhängigkeiten heute nur `fli` und `rich`. Neue
  Laufzeit-Abhängigkeiten nur für den interaktiven Modus (D11), und dort
  nur als optionales Extra.
- Remote ist `origin` → `github.com/xaniox/flight-search` (Repo meines
  Freundes). Ich habe dort Push-Rechte.

## Entscheidungen

### D1 – Vorgehen: Umbau hier, Stacked PRs, Fork als Rückfallebene

Der Umbau erfolgt in diesem Repo (heute kein Fork). Jede Änderung ist ein
eigener, kleiner PR. Alle Branches liegen in `xaniox/flight-search`, und
jeder PR zielt auf den Branch des vorherigen PRs (der erste auf `main`).
So zeigt jeder PR nur seine eigene Änderung. Übernimmt mein Freund die
PRs nicht, behalte ich das Repo als Fork.

Daraus folgt: Jeder PR ist für sich lauffähig, hat grüne Tests, eine
klare Beschreibung und ändert das Verhalten für die Defaults meines
Freundes nur, wenn der PR genau das zum Thema hat und es in der
Beschreibung steht.

Ursprünglich sollten reine Umbauten und neue Features nie im selben PR
stehen. Um die Zahl der PRs klein zu halten, habe ich mich bewusst für
**sechs PRs** entschieden (siehe PR-Reihenfolge). Innerhalb eines PRs
gilt deshalb: Umbau und Feature stehen in **getrennten Commits**, Umbau
zuerst. Jede Verhaltensänderung steht in der PR-Beschreibung.

### D2 – Keine Kettenplanung, sondern drei Bausteine

Statt eines Routenplaners gibt es drei Bausteine, die ich kombiniere:

1. Airline-Filter für jede Suche.
2. Gabelflug: hin zu Stadt A, zurück ab einer anderen Stadt B.
3. Einweg-Weiterflugsuche („next hop“).

### D3 – Airline-Filter

- Neue Option für eine Liste erlaubter Airlines (IATA-Codes), z. B.
  `A3,OA`. Sie gilt für alle Suchtypen.
- Der Filter wird an Google geschickt (`FlightSearchFilters.airlines`),
  damit die knappen Ergebnisplätze nicht von anderen Airlines belegt
  werden.
- Zusätzlich prüft das Tool lokal **jedes Segment** einer Verbindung
  (laut den von Google gelieferten Leg-Daten). Grund: Was Google bei
  Umsteigeverbindungen und Codeshares unter dem Filter versteht, ist
  nicht dokumentiert. Für Mileage Runs zählt aber jedes einzelne Segment.
  In der Testsuche vom 2026-11-27 kamen bei MUC→HER gemischte
  Verbindungen vor (GQ + A3).
- **Verkaufende und ausführende Airline:** `fli` liefert pro Segment
  die Airline der Flugnummer (`airline`) und die ausführende Airline
  (`operating_airline`). `operating_flight_number` ist im gepinnten
  `fli` immer `None` (`fli/search/_decoders.py`, `_parse_leg`). Heute
  speichert das Tool nur die verkaufende Airline. Künftig werden **beide** in `LegInfo`, im Cache und
  im JSON gespeichert, unabhängig davon, ob ein Airline-Filter aktiv ist.
  Alte Cache-Einträge ohne diese Felder gelten als ungültig bzw. werden
  neu geladen.
- **Filterregel:**
  - Standard (streng): Bei jedem Segment müssen **sowohl** die
    verkaufende **als auch** die ausführende Airline in der Liste stehen.
    Codeshares mit fremdem Flugzeug fallen also heraus.
  - Option `--allow-codeshare`: Es reicht, wenn die **verkaufende**
    Airline (Flugnummer) in der Liste steht. Die ausführende darf
    abweichen.
  - Fehlt die Angabe zur ausführenden Airline (`operating_airline is
    None`), gilt die verkaufende als ausführende. **(Claudes
    Entscheidung)** Grund: `fli` setzt `None`, wenn Google keinen
    abweichenden Betreiber meldet, also im Normalfall eines eigenen
    Flugs. Dieselbe Lücke entsteht leider auch, wenn der Code des
    Betreibers nicht im `Airline`-Enum von `fli` steht. Das ist selten,
    und es auszuschließen hieße, Googles Rohdaten an `fli` vorbei zu
    lesen. Das ist bewusst nicht vorgesehen.
  - `fli` liefert außerdem `self_transfer` pro Verbindung (Umstieg auf
    eigenes Risiko, getrennte Tickets). Solche Verbindungen werden in
    der Anzeige markiert, aber nicht ausgefiltert. **(Claudes
    Entscheidung)**
- In der Anzeige (D6) wird die ausführende Airline zusätzlich gezeigt,
  wenn sie von der verkaufenden abweicht.
- **Cache:** Die an Google geschickte Airline-Liste ändert die Anfrage
  und gehört deshalb in den Cache-Schlüssel (Phase 1 und Phase 2).
  `--allow-codeshare` ändert die Anfrage nicht und gehört nicht hinein.
  Die Segmentprüfung läuft lokal auf den gecachten, ungefilterten
  Flügen. Das funktioniert auch in Phase 1, weil Phase 1 künftig
  ebenfalls vollständige Flüge cacht (D9). So landen gemischte
  Verbindungen (GQ + A3) nicht schon in Phase 1 als günstigster Preis in
  der Shortlist.
- Allianz-Filter und Ausschlusslisten sind nicht gefordert. Ob sie
  „nebenbei“ mit durchgereicht werden, entscheidet der Umsetzer.

### D4 – Gabelflug über verschiedene Städte

- Hinflug Heimat → Stadt A, Rückflug Stadt B → Heimat, A ≠ B erlaubt.
  Die Zeit dazwischen fülle ich selbst (eigene Flüge, Fähre).
- A und B werden jeweils aus einer eigenen Zielauswahl gewählt
  (Länder, Flughafencodes, Umkreis), z. B. Hinflug nach `CY`, Rückflug
  ab `GR`.
- Weekday-, Nächte- und Zeitfenster-Regeln gelten wie bei der heutigen
  Wochenendsuche.
- **Ergebnisform:** eine Zeile pro Kombination (Ankunftsstadt A,
  Rückflugstadt B, Datumspaar), sortiert nach Gesamtpreis. Für Vielfalt
  gibt es eine Obergrenze, wie oft dieselbe Stadt A und dieselbe Stadt B
  in der Shortlist bzw. Ausgabe vorkommen dürfen (analog `--per-city`).
  Sonst bestünde die Liste nur aus „billigster Hinflug + jeder
  Rückflugort“.
- Phase 1 liefert Hin- und Rückpreise ohnehin getrennt pro Flughafen.
  Die Kandidaten (A, B, Datumspaar) lassen sich daraus ohne neue
  Discovery-Requests bilden.
- **Bestätigung in Phase 2 (Claudes Entscheidung):** Hin- und
  Rückflugsuchen werden pro (Stadt, Datum, Richtung) einzeln
  durchgeführt und gecacht, nicht pro Paar. Bestätigt werden also nur so
  viele Städte und Daten wie nötig. Die Paare entstehen lokal. Damit
  bleibt die Request-Zahl ungefähr linear in der Zahl der
  Shortlist-Städte und wächst nicht mit A × B.
- Das heutige Verhalten (Open-Jaw nur innerhalb einer Metro-Region)
  bleibt der Default, wenn keine eigene Rückflug-Auswahl angegeben ist.
- **Optionaler Preisvergleich mit einem Gabelflug-Ticket:** Gesucht wird
  immer mit zwei Einweg-Tickets. Für die angezeigten Top-Treffer kann das
  Tool optional den Preis als **ein** Gabelflug-Ticket („Mehrere Städte“)
  abfragen und die Differenz zeigen, analog zu `--compare-roundtrip`. Das
  kostet nur wenige zusätzliche Requests, weil es nur für die angezeigten
  Zeilen läuft. Unterstützt `fli` Mehrstrecken-Suchen nicht sauber,
  entfällt die Option. Dann bleibt der kombinierte Google-Flights-Link,
  der beide Flüge bereits als ein Ticket öffnet.
- Für die Segmente ist es egal, ob die Flüge auf einem Ticket oder auf
  zweien stehen. Umstiege innerhalb eines Einweg-Tickets sind geschützt.
  Anschlüsse zwischen getrennten Tickets baut das Tool nicht.

### D5 – Einweg-Weiterflugsuche („next hop“)

- Eigenes Kommando: Einweg ab einem festen Abflugort (ein oder mehrere
  Flughäfen, z. B. `LCA` oder `LCA,PFO`) zu einer Zielauswahl (Länder,
  Codes, Umkreis um den Abflugort).
- Datum fest oder als Zeitraum mit Wochentagen. Zeitfenster für den
  Abflug wie heute.
- Mit Airline-Filter (D3).
- Ergebnis: günstigste Verbindungen, nach Preis sortiert, mit
  Umsteige-Darstellung (D6).
- Die Abflugorte müssen nicht in der Nähe meines Wohnorts liegen. Das
  Kommando darf also nicht an der Heimat-Konfiguration hängen.
- **Ablauf (Claudes Entscheidung):** ein einziger Durchlauf über die
  Ziel-Batches pro Datum, ohne Bestätigungsphase. Eine Einweg-Anfrage
  liefert bereits konkrete Flüge. Eine zweite Phase würde die Requests
  etwa verdoppeln. Ergebnis: **eine Zeile pro Zielstadt** mit dem
  günstigsten passenden Flug, sortiert nach Preis. Aufgeklappt bzw. mit
  `--verbose` erscheinen die weiteren gefundenen Flüge zu dieser Stadt.
  Weil eine Batch-Anfrage nur die günstigsten Zeilen liefert, ist diese
  Liste nicht vollständig. Das steht in der Hilfe.
- **Zielauswahl (Claudes Entscheidung):** Next-Hop nutzt den
  **weltweiten** Datensatz, nicht die Default-Region `europe`. Ein
  Umkreis um LCA findet also auch Tel Aviv oder Beirut.
  `--exclude-countries` wirkt auch hier.

### D6 – Darstellung von Umsteigeverbindungen

Probleme der heutigen Ausgabe (Testsuche vom 2026-11-27):

- Umstiege über Nacht sind nicht erkennbar. Es fehlt das Datum je
  Segment (`MUC→ATH 11:05–14:35 · ATH→HER 13:25–14:20`, der Anschluss ist
  am Folgetag). Auch die Zusammenfassung `13:00–08:00` zeigt nicht, dass
  die Ankunft einen Tag später ist.
- Die Tabelle bricht bei schmalen Terminals unübersichtlich um.
- ATH wird als „Spata-Artemida“ angezeigt (fehlender Eintrag in
  `[names]`).

Für alle Suchtypen zeigt die Tabelle pro Richtung:

- die Route mit allen Zwischenstopps (`LCA→ATH→RHO`),
- die Zahl der Segmente,
- die Airline pro Segment (`A3/OA`),
- Umsteigeort und Umsteigezeit (`ATH 1h35`),
- einen sichtbaren Hinweis, wenn Ankunft oder Anschluss an einem späteren
  Tag liegen.

In der Detailansicht (`--verbose`) steht bei jedem Segment das Datum.
Umstiege über Nacht sind ausdrücklich markiert.

**Verbindlich für die eingeklappte Tabelle (Claudes Entscheidung):**
Route mit Zwischenstopps, Segmentzahl, Airlines pro Segment und eine
Tagesmarkierung (`+1`), wenn Ankunft oder Anschluss an einem späteren Tag
liegen. Umsteigezeiten, Datum je Segment, abweichender Betreiber und
`self_transfer` stehen in der aufgeklappten Ansicht bzw. bei `--verbose`.
So bleibt die Tabelle schmal genug für normale Terminals.

Sortierung nach Gesamtpreis. **Keine** Spalte und keine Sortierung
„Preis pro Segment“. Das JSON bekommt Segmentzahl und Umsteigezeiten
zusätzlich. Bestehende Felder bleiben erhalten (Abwärtskompatibilität für
Skripte meines Freundes).

Beispiel eingeklappt (Gabelflug MUC → Zypern, zurück ab Griechenland):

```
#  Total  Hin                           Zurück                             Nächte  Seg
1  €214   Fr 12 Jun  MUC→ATH→LCA  A3/A3  So 21 Jun  RHO→ATH→MUC  OA/A3 +1     9      4
2  €231   Fr 12 Jun  MUC→ATH→LCA  A3/A3  So 21 Jun  HER→MUC      A3          9      3
```

Beispiel aufgeklappt:

```
1  €214   Zypern (Larnaka) ⇢ Rhodos                       9 Nächte · 4 Segmente
   Hin     Fr 12 Jun  A3 801  MUC 06:15 → ATH 09:45
                      ── Umstieg ATH 1h20 ──
           Fr 12 Jun  A3 902  ATH 11:05 → LCA 13:00        €129
   Zurück  So 21 Jun  OA 213  RHO 18:40 → ATH 19:35
                      ── Umstieg ATH 13h10 · über Nacht ──
           Mo 22 Jun  A3 804  ATH 08:45 → MUC 10:20        €85
   Links   gesamt · hin · zurück
```

Layout im Detail und Farben entscheidet der Umsetzer.

### D7 – Konfiguration und Wohnort

- Eine optionale Datei `~/.config/flight-search/config.toml` (bzw.
  `$XDG_CONFIG_HOME`) liefert Defaults für die CLI-Optionen:
  Heimatflughäfen, Heimatkoordinate, Währung, Land, Sprache, Umkreis,
  `include_small` usw. CLI-Optionen überschreiben die Datei.
- Ohne Datei verhält sich das Tool exakt wie heute (Karlsruhe,
  `FKB,STR,SXB,FRA`, keine kleinen Flughäfen).
- Der Mittelpunkt für Umkreis und km-Angaben kommt aus der Konfiguration
  statt aus der Konstante `KARLSRUHE_*`. Fehlt er, gilt Karlsruhe.
- Benannte Regionen (z. B. Länderlisten) in der Config sind
  wünschenswert, weil Ziele außerhalb der Default-Region (Tel Aviv,
  Beirut, Amman …) sonst jedes Mal per `--countries` angegeben werden
  müssen. Benannte Profile sind optional.
- Eine optionale Overlay-Datei für eigene Metro-Gruppen und Namen im
  Config-Verzeichnis ist wünschenswert, aber nicht Pflicht.

### D7a – Kleine Flughäfen

- Flughäfen, die ausdrücklich per Code genannt werden (`--dest`,
  Rückflug-Auswahl, Next-Hop-Abflugort), werden **immer** berücksichtigt,
  auch wenn sie im Datensatz als `small_airport` geführt sind. Heute
  führt das zu „Unknown or unsupported destination code“.
- Für Länder-, Regions- und Umkreisauswahl gilt weiter `--include-small`.
  In meiner Config setze ich `include_small = true` als Default. Grund:
  Viele Olympic-Ziele (Kasos, Leros, Astypalea, Kalymnos, Ikaria, Milos,
  Naxos, Paros, Syros, Limnos, Skyros) sind `small_airport`.
- Default ohne Config bleibt: keine kleinen Flughäfen.

### D8 – Datensatz weltweit, Region zur Laufzeit

- Heute filtert `refresh.py` beim Erzeugen nach `continent == "EU"` plus
  einer Länderliste. Dadurch fehlen u. a. **Rhodos (RHO) und Kos (KGS)**
  (OurAirports: `continent = AS`), **Zypern** (LCA, PFO) und die
  **Kanaren** (`continent = AF`). Der Eintrag `[metros.tenerife]` greift
  deshalb ins Leere.
- Neu: Der Datensatz enthält **alle** Linienflughäfen weltweit mit
  IATA-Code, die `fli` kennt. **(Claudes Entscheidung, von mir
  begrüßt: weitere Aegean-Ziele sollen erreichbar sein.)**
- Die Default-Region `europe` wird zur Laufzeit gefiltert und folgt der
  **heutigen Regel** (OurAirports `continent == "EU"` plus Nordafrika,
  Türkei, Kaukasus). Zusätzlich sind **Griechenland, Zypern, Spanien und
  Portugal komplett** enthalten, unabhängig vom Kontinent. Damit kommen
  Rhodos, Kos und die übrigen Dodekanes-Flughäfen, Zypern und die
  Kanaren dazu. Die Länderlisten stehen ausdrücklich im Code.
- **Russland** bleibt wie heute auf den europäischen Teil beschränkt
  (Kontinent-Regel). Sibirien und Fernost kommen nicht in die
  Default-Region.
- Das ist eine gewollte Korrektur. Die Request-Zahl für meinen Freund
  steigt leicht. Beides steht in der PR-Beschreibung, und das README
  (Flughafenzahlen) wird angepasst.
- **Länder ausschließen:** Neue Option `--exclude-countries` (z. B.
  `RU,BY`), auch als Default in der Config (D7) setzbar. Sie wirkt auf
  jede Zielauswahl (Region, Länder, Umkreis). Ich will damit Russland
  komplett ausschließen. Ohne Option bleibt alles wie oben.
- Ziele außerhalb der Default-Region (z. B. `IL`, `LB`, `JO`) sind über
  `--countries` bzw. benannte Regionen (D7) erreichbar. `--countries`
  wählt aus dem weltweiten Datensatz, nicht aus der Default-Region.
- **Umkreis bei der Wochenendsuche (Claudes Entscheidung):**
  `--region weekend` bleibt „Default-Region ∩ Umkreis um die
  Heimatkoordinate“. Für meinen Freund ändert sich dadurch nichts außer
  den gewollten Ergänzungen. Next-Hop nutzt dagegen den weltweiten
  Datensatz (D5).
- Die bereits vorhandene, nicht committete Änderung an `airports.csv`
  stammt von einem `refresh-airports`-Lauf nach README (Upstream-Drift:
  Koordinaten, Namen, `KLV` large → medium). Sie kommt als **eigener
  Commit** in PR 1, vor dem Commit mit der Datensatz-Erweiterung, damit
  beide Änderungen einzeln lesbar sind. Ein eigener PR ist nicht nötig.
- `refresh-airports` schreibt heute ins Paketverzeichnis. Das bleibt so
  (Entwicklerbefehl). Ob es einen Hinweis bei nicht-editierbarer
  Installation gibt, entscheidet der Umsetzer.

### D9 – Fehler im Discovery-Cache beheben

Der Cache-Schlüssel in Phase 1 (`discover.py`, `_batch_key`) enthält nur
die auf volle Stunden gekürzten `TimeRestrictions`. Gespeichert werden
aber minutengenau gefilterte Preise. Zwei Läufe mit `--depart-after 17:30`
und `17:00` teilen sich deshalb falsche Einträge.

Fix **(Claudes Entscheidung)**: Phase 1 cacht künftig die
**ungefilterten Flüge** pro Batch (wie Phase 2 mit
`FlightOption.to_dict()`), nicht mehr das gefilterte
`{Flughafen: Mindestpreis}`. Zeitfenster und später die Airline-Prüfung
(D3) laufen nach dem Cache. Das behebt den Fehler und ist gleichzeitig
die Grundlage für D3. Die Cache-Einträge werden größer (eine
Ergebnisseite pro Batch), das ist unkritisch. Alte Einträge im alten
Format werden ignoriert. Mit Regressionstest.

### D10 – Kern aus der CLI herauslösen

`_run_weekend` (`cli.py`, ~270 Zeilen) mischt Validierung, Planung, beide
Suchphasen und Ausgabe. Vor den neuen Features wird daraus:

- ein Request-Objekt (Dataclass) mit allen fachlichen Parametern,
- eine Such-Funktion ohne `argparse`, `rich` oder `print`, die ein
  Ergebnisobjekt liefert,
- die CLI nur noch für Parsen, Fortschrittsanzeige und Ausgabe.

Das Ergebnisobjekt enthält nicht nur die fertigen Kombinationen, sondern
auch die **vollständigen bestätigten Einzelflüge je Richtung** (alle
Hin- und Rückflug-Optionen pro Stadt und Datum, nicht nur den
günstigsten pro Flughafenpaar wie heute in `reduce_best`). Heute werden
sie nach der Kombination verworfen. Die Begrenzung auf die Top-N
(`pool_size`) wandert von der Suche in die Anzeige. Der interaktive Modus
(D11) braucht diese Listen. Zusätzliche Requests entstehen dadurch
nicht.

**Gefiltert oder ungefiltert (Claudes Entscheidung):** Das Ergebnisobjekt
hält die Flüge **vor** den lokalen Filtern (Zeitfenster,
Airline-Segmentprüfung) und dazu die Filterparameter der Suche.
Kombination und Filter sind Funktionen, die Tabelle, JSON und TUI darauf
anwenden. Die TUI wendet in D11 dieselben Filter an. Filter in der TUI
zu lockern ist nicht gefordert, wird so aber später möglich, ohne neue
Requests.

Nebenbei: doppelten Code zusammenführen (`_restrictions_key` in
`discover.py` und `detail.py`, Hin-/Rück-Zweige im Discovery-Worker),
ungenutztes `RunPlan` entfernen. Verhalten und Ausgabe bleiben
unverändert. Ob Phase 2 parallelisiert wird, entscheidet der Umsetzer.
Das gehört dann in einen eigenen PR.

### D11 – Interaktiver Terminal-Modus (letzter Schritt)

- Optionaler Modus (z. B. `--tui`), umgesetzt mit **Textual** (gleicher
  Hersteller wie `rich`) **(Claudes Entscheidung)**. Textual ist ein
  optionales Extra (`flight-search[tui]`), keine Pflicht-Abhängigkeit.
  Ohne die Option bleibt die Ausgabe wie in D6.
- Zwei Ansichten, umschaltbar:
  1. **Fertige Paare:** die günstigsten Kombinationen wie in der
     Tabellenausgabe, jede Zeile aufklappbar (Segmente, Umstiege, Links).
  2. **Hinflug zuerst:** Liste aller bestätigten Hinflüge mit eigenem
     Preis und Gesamtpreis „ab“ (mit dem günstigsten passenden
     Rückflug). Auswahl eines Hinflugs zeigt alle passenden Rückflüge
     (Datum, Nächte, Zeitfenster, bei Gabelflug auch andere Städte) mit
     Gesamtpreis, sortiert nach Gesamtpreis, ebenfalls aufklappbar.
- Für Next-Hop (Einweg) gibt es nur eine Liste mit aufklappbaren Zeilen.
- **Kein Nachladen:** Der Modus zeigt vorerst nur, was die Suche bereits
  geladen hat, und schickt keine weiteren Anfragen an Google. Nachladen
  kann später ergänzt werden.
- Das kostet keine zusätzlichen Requests: Phase 2 lädt pro (Stadt, Datum,
  Richtung) ohnehin die komplette Ergebnisseite. Das Ergebnisobjekt (D10)
  liefert diese vollständigen Listen mit, und alle Kombinationen,
  Gesamtpreise und Filter entstehen lokal bei der Anzeige. Grenze: Es
  gibt nur Flüge für Städte und Daten, die es in die Shortlist von
  Phase 2 geschafft haben. Phase 1 kennt nur Preise pro Flughafen und
  Tag, keine konkreten Flüge.
- Links lassen sich aus der Ansicht im Browser öffnen.

## PR-Reihenfolge

Sechs PRs. Jeder setzt auf dem Branch des vorherigen auf. Innerhalb eines
PRs sind die Themen auf **getrennte Commits** verteilt, damit mein Freund
Schritt für Schritt lesen kann.

| # | PR | Commits (Themen) | Verhalten für Defaults |
|---|---|---|---|
| 1 | **Fixes & Daten** | Cache-Fix Discovery (D9) · vorhandener OurAirports-Refresh · Datensatz weltweit, Region nach Ländern (D8) · Namen (ATH) | korrigiert; Rhodos, Kos, Zypern, Kanaren neu; leichte Drift |
| 2 | **Basis: Such-Kern & Konfiguration** | Duplikate und `RunPlan` entfernen · Such-Kern aus der CLI lösen, vollständige Fluglisten im Ergebnis (D10) · Heimatkoordinate statt Karlsruhe-Konstante · Config-Datei mit Regionen und `include_small` (D7) · explizit genannte kleine Flughäfen immer nutzen (D7a) · `--exclude-countries` inkl. Config-Default (D8) | unverändert ohne Config; `--dest` mit kleinen Flughäfen funktioniert |
| 3 | **Umsteigeverbindungen & Airline-Filter** | Umsteige-Darstellung (D6) · Airline-Filter mit Prüfung jedes Segments (D3) | Tabelle erweitert; Filter nur mit Option |
| 4 | **Next-Hop** | Einweg-Weiterflugsuche (D5) | neues Kommando |
| 5 | **Gabelflug** | Rückflug ab anderer Stadt, Paare mit Vielfalts-Grenze · optionaler Preisvergleich mit einem Gabelflug-Ticket (D4) | unverändert ohne Option |
| 6 | **Interaktiver Modus** | Textual als Extra, beide Ansichten (D11) | unverändert ohne Option |

PR 1 ist für meinen Freund auch allein nützlich. PRs 4–6 sind die
Features, die er einzeln ablehnen kann.

## Dem Umsetzer überlassen

- Namen von Kommandos und Optionen (z. B. `oneway` oder `next`,
  `--airlines`, `--return-dest`, `--tui`), solange sie zum bestehenden
  Stil passen.
- Genaues Tabellenlayout, Farben und Tastenbelegung im interaktiven
  Modus.
- Interne Struktur des Request-/Ergebnisobjekts und Modulaufteilung.
- Konkrete Obergrenzen für die Vielfalt beim Gabelflug (D4).
- Ob Allianz-Filter gleich mit durchgereicht werden.
- Ob Phase 2 parallelisiert wird (eigener PR).
- Werkzeug für Stacked PRs (`gh`, `git-spice`, manuell).
