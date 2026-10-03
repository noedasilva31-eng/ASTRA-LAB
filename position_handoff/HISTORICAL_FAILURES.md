# Erreurs historiques séparées — run Windows fourni

Les rapports Windows conservent des FAIL V1c/V1d/V1e
`devnet_identity_not_verified`, puis `previous_phase_failed` pour les phases
suivantes. Integrated conserve `pipeline_exception ValueError @ rpc.py:75 context`.
Ces FAIL ne sont ni remplacés par les tests locaux ni attribués à Position Brain.

Le code à rpc.py:75 lève `devnet_identity_not_verified` si l'appel getGenesisHash
renvoie une erreur de transport, OU si sa valeur n'est pas le genesis Devnet attendu.
La localisation Integrated correspond à ce même prédicat de vérification.
Le rapport ne suffit pas à distinguer ces deux branches. Le ZIP n'apporte pas
les bruts getGenesisHash de ces phases Devnet permettant de prouver laquelle.
Aucune cause externe plus précise (endpoint, réseau, configuration) n'est inventée.

Une future analyse demanderait les archives de ces seules phases avec réponses
getGenesisHash ou code d'erreur transport nettoyé, sans URL complète ni credential.
Aucun changement dans rpc.py, les contrôles Devnet, Brain ou Risk pour les masquer.

Observer HTTP/WSS et le Bridge dédié restent les preuves Windows fournies. Le
Position Brain V0.2 ajouté ici n'a pas été exécuté sur Mainnet dans Work.
