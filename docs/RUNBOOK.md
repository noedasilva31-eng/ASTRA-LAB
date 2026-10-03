# Runbook V1a offline

Python >=3.12, aucune dépendance tierce. Depuis la racine décompressée :

```bash
python3 -m unittest discover -s tests -v
python3 -m astra --db var/astra.sqlite ingest fixtures/events.jsonl
python3 -m astra --db var/astra.sqlite health
python3 -m astra --db var/astra.sqlite recover
python3 -m astra --db var/astra.sqlite as-of --at 1800000000000000
python3 -m astra --db var/astra.sqlite snapshot --at 1800000000000000
python3 -m astra --db var/astra.sqlite backup var/backup.sqlite
```

Remplacer le cutoff d'exemple (microsecondes UTC) pour la date souhaitée. Les deux lignes de fixture sont synthétiques et identiques : une publication, un doublon. Les relectures ajoutent des captures sans republier. Le journal n'est pas un collecteur global ni un moteur de trading.

Sortie 2 : ingestion avec quarantaine ou health dégradé. Autres erreurs : sortie non nulle, diagnostics encore non uniformisés. `recover` reprend les étapes du journal, pas un feed réseau. Après incident : stopper ingestion, conserver base/WAL, exécuter health, sauvegarder via l'API backup, inspecter raisons de quarantaine. Ne pas supprimer des lignes pour rendre health vert. Restaurer dans un nouveau fichier puis comparer snapshots/hashes.

Health parcourt les hashes, coût O(n) : audit, pas liveness haute fréquence. Aucun daemon, serveur HTTP, watchdog, métriques exportées ou alertes installés. Le backup local ne protège pas d'une perte du volume. Les triggers ne protègent pas d'un administrateur malveillant.

JSONL accepte des records déjà structurés, pas des blocs RPC bruts. Adaptateurs et schémas métier Solana à construire. Ne pas antidater les imports historiques. Aucun secret nécessaire ; les futurs identifiants seront injectés via secret manager, jamais inclus dans le chat, les fixtures ou les logs.
