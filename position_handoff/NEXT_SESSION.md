# Point de reprise courant — Position Brain V0.2

## Ce qui est terminé

Module astra_position séparé : import atomique vérifié de l'OPEN_POSITION réel,
activation versionnée, thèse historique liée au BUY, PositionHealth temporelle,
candidature de sortie sur détérioration conjointe persistante, Evidence/Risk/ledger
qualifiés pour SELL et règlement postérieur. Aucun nouveau BUY ni découverte.
Rapport/replay hors réseau, revue post-trade, budget persistant et suivi ciblé HTTP.
Tests de reprise, refus, idempotence, fermeture synthétique explicitement de test,
corruption et échéances avant/après acquisition. Résultats exacts dans report.json.

## Preuve de référence et état à préserver

Run Windows fourni all-validation-jyqge_an, copié sans modification dans
position_reference/. 51 plans/snapshots reconstruits; freeze vérifié hors réseau.
Une position, ledger sequence=2; quantité 4 624 230 unités brutes, coût paper
12 100 000 lamports, cash 987 900 000 lamports, aucun SELL. Le montant de frais
simulés BUY reste 2 100 000 lamports. Ne pas réinitialiser ce portefeuille.

position_handoff/offline-resume/ contient une copie auditée hors réseau.
Ne pas la confondre avec une nouvelle observation Mainnet. Les 11 PositionHealth
rétrospectives du rapport ont toutes HOLD; ce sont des analyses V0.2 des anciennes
preuves, pas des décisions exécutées par V0.2 lors du run Windows.

## Première action suivante (quand une session live sera décidée)

Aucune validation ni découverte supplémentaire demandée maintenant.
Pour poursuivre exclusivement cette position, utiliser resume-position-windows.cmd.
Le dossier opérationnel sera position-continuation/, créé depuis la référence,
puis réutilisé sans reset à chaque reprise. Les endpoints restent dans l'environnement.
Pas de WebSocket requis pour ce suivi ciblé, aucune clé à inscrire dans les fichiers.

120 s, 16 polls, allocation séparée de 80 appels/quotes; précédent 188/200 conservé.
Le budget et la fenêtre ne sont pas rechargés par une relance. Une fois épuisés,
préparer un futur mécanisme d'allocation explicite si nécessaire; ne pas modifier
les compteurs à la main. Pas de fermeture forcée.

Conserver position-report.json, position-review.json et les trois SQLite avec
leurs éventuels WAL. Examiner raison d'arrêt, derniers états, raisons HOLD/VETO,
fraîcheur, quote à taille entière et état du ledger. OPEN_POSITION ou PENDING_SELL
sont des résultats légitimes. Aucun objectif de SELL ni modification de seuil.

## Frontières non qualifiées

V0.2 Windows/Mainnet : NOT_EXECUTED. Profondeur garantie, MAE/MFE exécutables
complets, frais effectivement payés, outcome futur non observé : UNKNOWN.
Les frais du modèle restent SIMULATED. Aucun ordre réel.

Les FAIL Devnet et Integrated rpc.py:75 sont conservés dans HISTORICAL_FAILURES.md
et reference-audit.json. Leur résolution n'appartient pas à ce sprint.
Pas de Wallet/X/KOL/UI/agents. Pas d'ajustement automatique de paramètres.

Le NEXT_SESSION.md racine est une ancienne référence hashée. Ce document est
le seul point de reprise courant pour Position Brain V0.2.
