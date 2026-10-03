# Point de reprise exact

1. Extraire `ASTRA-V1c-rpc-v1-fix.zip` dans un nouveau dossier ; ne remplacer
   aucune base ni l’archive V1b officielle.
2. Avec SOLANA_RPC_URL déjà définie vers Devnet, lancer :
   `.\validate-blocks-windows.cmd`
   La commande exécute toute la validation et appelle le gate V1b inchangé.
3. Exiger 35/35 tests V1c, 38/38 dépôt, 8/8 runner, contrôle Devnet réel complet,
   replay hors réseau et les 14 critères V1b PASS. Aucun PASS Windows/live n’est
   revendiqué avant ce résultat. Ne pas relancer des vérifications manuelles.
4. Si -32015 subsiste : les diagnostics fournissent le plafond envoyé (1), le
   code et, si extractible, le numéro de version annoncé. Ne pas augmenter la
   version au-delà de ce qui est explicitement supporté ni déclarer skipped.
5. Si -32603 persiste après les trois passes : conserver FAIL, les captures et
   les métadonnées de requête ; il s’agit d’une erreur interne non résolue,
   sans diagnostic automatique du composant serveur à partir du seul code.
6. Une fois le gate réel entièrement PASS, reprendre les dépendances V1 de
   `docs/TESTING_ACCEPTANCE.md` (décodeur métier sur les transactions archivées).

La baseline officielle et tous ses tests sont toujours inchangés. Le test
clock_regression_fail_closed était PASS dans les deux pièces Windows reçues ;
aucune correction spéculative de l’horloge n’a été introduite.
