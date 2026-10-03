# Reprise — ASTRA-V1-live-session

Point de départ : ASTRA-V1-token-evidence qualifié par l'utilisateur Windows/Mainnet
pour Observer et Evidence Bridge ; round-trip encore NOT_EXECUTED. Rapport utilisateur
74buueu_ mentionné mais non joint. Ne pas refaire ces composants.

Ajout isolé : session.py, découverte WebSocket puis suivi ciblé du pool dès qu'une
intention/position existe. Réutilise intégralement Evidence/Risk/ledger. Preuves de
règlement postérieures, aucune réutilisation artificielle de transaction ou date.
Les états sans preuve restent ouverts, mesurés et non qualifiés pour le round-trip.

Première action : `validate-all.cmd` dans ce nouveau dossier Windows. Les variables
existantes suffisent. Lire la ligne Bridge qui indique maintenant phase, nombre
de BUY/SELL, polls et hydratations ; détails dans bridge-report.json et frames
paper_session_* du raw.sqlite. Ne pas attendre nécessairement un round-trip PASS.

Si la fenêtre finit en PENDING_BUY ou PENDING_SELL, examiner les ticks et refus :
absence de transaction plus récente, signatures déjà traitées, hydratation nulle,
quote périmée, impact, autorités, réseau ou budget. Ne pas supposer une cause
avant lecture des preuves. Les comptages permettent cette distinction.

Préserver les rapports réels. Ne pas agrandir arbitrairement les TTL, diminuer les
vetos ou fabriquer une sortie. Pas d'UI, d'agents ou d'intégration sociale à ce jalon.
Le suivi met temporairement en pause la découverte globale : couverture PARTIAL.
Une découverte et un suivi réellement concurrents seraient une étape séparée.
