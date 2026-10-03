# Reprise — ASTRA-V1-context / Brain V0.1

406/406 tests locaux PASS, dont 20 nouveaux. Gate locale complète PASS sous Linux.
Gate globale FAIL: endpoints absents dans Work. Windows/Mainnet V0.1 NOT_EXECUTED.
36 fichiers protégés identiques, y compris Observer/Evidence/Risk/Bridge/ledger et Brain V0.

## Première action suivante

Sur Windows avec les endpoints déjà configurés, exécuter `validate-all.cmd` à la
racine. Conserver le dossier all-validation complet, notamment context-proofs,
SQLite, session-dataset.json, context-report.json, freezes et rapports.
Devnet/Mainnet restent séparés: voir README_CONTEXT.md.

Examiner Context / real_context_session: candidats admissibles, required_missing,
scores/décompositions, régimes, watches, raisons d'abandon, budgets et replay.
Zéro trade ne prouve pas un round-trip. Aucune absence d'événement ne devient PASS.
Reprise: même dossier Context et commande README_CONTEXT; ne pas convertir une
session Brain V0 en V0.1. Aucun changement de seuil destiné à provoquer un BUY.

## Accompli

Contexte temporel borné, UNKNOWN/STALE explicites, momentum/volatilité/drawdown,
activité/réserves, régime déterministe, scoring conditionnel sans changement
économique, hydratation ciblée persistante, expiration contrôlée même pendant
acquisition, replay et SessionFreeze. Rapport read-only V0/V0.1 et gate étendue.

51 décisions réelles V0 rejouées, freeze vérifié. Quatre Evidence-PROVEN: un seul
swap dans le pool et momentum_bps absent, quotes fraîches. Audit de 23 devises:
21 orientations WSOL-base potentiellement normalisables ultérieurement; 2 sans
jambe WSOL. Aucun support élargi.

## Limites

UNKNOWN: profondeur exécutable garantie, confiance calibrée, couverture complète,
âge non prouvé et MAE/MFE exécutables complets. Aucune performance améliorée prouvée.
Les FAIL historiques Windows (identité Devnet/Integrated/Bridge) restent consignés
séparément dans REFERENCE_AUDIT.md, sans déclaration de correction.
Aucune calibration pendant une session, aucun Wallet/X/KOL/UI/agent complexe.
Les NEXT_SESSION.md et README.md racine sont des références historiques hashées;
ce document est le point de reprise courant.
