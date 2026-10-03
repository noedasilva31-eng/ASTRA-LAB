# ASTRA-V1-live-session

Validation Windows unique : `validate-all.cmd`.

Installation préalable du streaming : `py -3 -m pip install -r requirements-observer.txt`.
Le package est **websocket-client** ; le module importé est `websocket`.
Le validateur ne modifie pas automatiquement l'environnement Python.

- Sprint et limites : [EVIDENCE_BRIDGE.md](EVIDENCE_BRIDGE.md).
- Reprise actuelle : [bridge_handoff/NEXT_SESSION.md](bridge_handoff/NEXT_SESSION.md).
- Rapports : `validation-summary.json`, `validation-summary.txt`.
- Preuves utilisateur de la baseline Windows : `bridge_handoff/WINDOWS_BASELINE_EVIDENCE.json`.

La référence ASTRA-V1-paper est conservée séparément. Les handoffs précédents,
y compris NEXT_SESSION.md racine, restent historiques pour préserver les manifestes.
Aucun contrôle Mainnet du nouveau pont n'est couvert par le PASS de l'ancienne version.

Correction ciblée : `bridge_handoff/FIX_DIAGNOSIS.md`.

Diagnostic courant sur captures réelles : `bridge_handoff/OBSERVED_TOKEN_DIAGNOSIS.md`.

Jalon courant : `bridge_handoff/LIVE_SESSION.md`.
