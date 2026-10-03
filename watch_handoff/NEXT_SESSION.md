# Reprise — ASTRA-V1-watch

## Travail accompli

Diagnostic ciblé : l'ancien watcher réutilisait la première fenêtre persistée
et le compteur global de polls. Après leur expiration/épuisement, une relance
pouvait effectuer zéro appel tout en affichant no_new_position_observation.
Ce comportement est reproduit par deux tests indépendants (temps et polls).
La première tentative Windows n'est pas diagnostiquable exactement sans son
dossier position-continuation, non fourni dans cette demande. Ne pas conclure
que le pool est inactif à partir de cette seule ligne.

Nouveau module astra_watch, sans modification du module astra_position ni des
composants qualifiés. Fenêtres explicitement identifiées, budgets archivés,
reprise même ID sans reset, nouvelle fenêtre avec nouvel ID, recherche de tête
32 signatures, plus récentes d'abord, curseur pool/mint exact, diagnostics des
six étapes, Ctrl+C propre, HOLD continu, Evidence/Risk/ledger inchangés.

## Première action suivante

Quand une observation Windows/Mainnet est souhaitée, depuis le nouveau dossier :

    resume-position-windows.cmd --seconds 120 --budget 80 --max-polls 60 --poll-seconds 2

Le dossier par défaut est position-continuation. Pour reprendre celui de la
version précédente, copier ce dossier ici ou fournir --directory avec son chemin.
Ne pas utiliser la référence immuable comme dossier actif.
Sans --window-id : nouvelle allocation bornée, explicitement journalisée.
Avec --window-id égal à l'ID affiché et les mêmes bornes : reprise de cette fenêtre,
pas de nouveau budget. Une fenêtre expirée reste expirée. Ctrl+C est supporté.

Conserver watch-report.json, watch-review.json et les SQLite/WAL du dossier actif.
Lire en priorité network_attempted, cursor_slot, latest_slot_seen,
signatures_found, transactions_hydrated, position_observations, stage,
stop_reason et rejection_reasons. Aucune recherche ne parcourt toute la chaîne;
la couverture est la tête observée, pas une preuve d'inactivité globale.

## Preuves/limites

La position de référence reste OPEN_POSITION : 4 624 230 unités brutes,
coût 12 100 000 lamports paper, cash 987 900 000, ledger sequence=2.
Migration et replay des 51 plans testés hors réseau. Aucun nouveau BUY réel ou
paper de production; les sorties des tests sont des fixtures synthétiques.
Nouveau watcher Windows/Mainnet NOT_EXECUTED dans Work. Les FAIL historiques
Devnet/Integrated restent présents, sans modification de Brain/Risk pour les masquer.
Le nombre exact de tests et la gate finale sont dans report.json/validation-summary.json.

Aucun Wallet/X/KOL/UI/agents. Aucun ordre réel, observation inventée ou SELL forcé.
Le NEXT_SESSION.md racine et les anciens handoff sont des références historiques;
ce document est le point de reprise courant.
