# Reprise exacte — ASTRA-V1-observatory

Référence externe inchangée : ASTRA-V1-operations, 225 tests Windows/Helius Devnet
PASS selon le résultat utilisateur postérieur au ZIP. Ce n'est pas une preuve locale.

Terminé localement : nouveau chemin Mainnet/Devnet READ ONLY à genesis explicite ;
archive de transactions/notifications avant décodage ; budget persistant O(1) ;
adaptateur WSS logsSubscribe + hydratation HTTP bornée ; moteur incrémental commun
live/replay ; census de tous les pools décodés ; OpportunityState partiel ; features
par fenêtre bornée ; outcomes aussi pour opportunités refusées ; veto Risk et journal
NO_TRADE ; reprise/idempotence/conflits ; comparaison de reconstruction ; benchmarks.

Première action réelle : configurer séparément ASTRA_OBSERVER_NETWORK=mainnet,
ASTRA_OBSERVER_RPC_URL et éventuellement ASTRA_OBSERVER_WS_URL dans l'environnement,
installer requirements-observer.txt pour WSS, puis exécuter validate-all.cmd.
SOLANA_RPC_URL conserve son endpoint Devnet historique. La gate archive ses preuves.
Work n'avait aucun endpoint utilisateur ; le RPC public a échoué au transport.
Ne pas requalifier cet échec comme un PASS ni une absence d'activité PumpSwap.

Première action de code : confronter le décodeur à une capture réelle archivée et
identifier exactement les formats/CPI non reconnus. Ensuite ajouter un adaptateur
d'événements transactionnels à faible latence / file bornée avec réconciliation et
backfill des gaps, puis launch/bonding/migration. Préserver les deux chemins archive
lourd et traitement incrémental. Les tests ciblés sont dans observer_tests.

Étape permettant les premières positions paper : fournisseur de cotation prouvée,
état autorités/risques et santé/couverture du feed ; modèle documenté d'impact/frais/
latence/sortie ; portefeuille paper et journal entrée-sortie-PnL. La stratégie
actuelle est observe-v1, toutes ses décisions NO_TRADE. Ne pas les présenter comme
des trades simulés remplis. Outcomes actuels = marks partiels, non prix liquidables.

Lancer la gate complète à l'intégration, sans modifier les anciennes baselines.
Les fichiers NEXT_SESSION des anciens handoffs/racine restent historiques ; ce
fichier est le point de reprise courant. V1 n'est pas terminée.
